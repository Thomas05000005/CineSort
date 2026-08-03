"""Tests pour le decorateur requires_valid_run_id (issue #101)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import cinesort.ui.api._validators as _validators
import cinesort.ui.api.cinesort_api as cinesort_api
import cinesort.ui.api.export_support as ui_export_support
from cinesort.ui.api._validators import is_valid_run_id, requires_valid_run_id


class RequiresValidRunIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = MagicMock()

    def test_valid_run_id_calls_wrapped_function(self) -> None:
        self.api._is_valid_run_id.return_value = True
        called = []

        @requires_valid_run_id
        def f(api, run_id):
            called.append(run_id)
            return {"ok": True, "run_id": run_id}

        result = f(self.api, "20260101_120000_001")
        self.assertEqual(result["ok"], True)
        self.assertEqual(called, ["20260101_120000_001"])

    def test_invalid_run_id_returns_error_dict_without_calling_wrapped(self) -> None:
        self.api._is_valid_run_id.return_value = False
        called = []

        @requires_valid_run_id
        def f(api, run_id):
            called.append(run_id)
            return {"ok": True}

        result = f(self.api, "bad-id")
        self.assertFalse(result["ok"])
        self.assertEqual(result["run_id"], "bad-id")
        self.assertIn("message", result)
        self.assertEqual(called, [])

    def test_none_run_id_returns_error(self) -> None:
        self.api._is_valid_run_id.return_value = False

        @requires_valid_run_id
        def f(api, run_id):
            return {"ok": True}

        result = f(self.api, None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["run_id"], "")

    def test_keyword_run_id_works(self) -> None:
        self.api._is_valid_run_id.return_value = True

        @requires_valid_run_id
        def f(api, run_id):
            return {"ok": True, "rid": run_id}

        result = f(self.api, run_id="20260101_120000_001")
        self.assertEqual(result["rid"], "20260101_120000_001")

    def test_extra_args_passed_through(self) -> None:
        self.api._is_valid_run_id.return_value = True

        @requires_valid_run_id
        def f(api, run_id, extra, *, kw):
            return {"run_id": run_id, "extra": extra, "kw": kw}

        result = f(self.api, "20260101_120000_001", "abc", kw="def")
        self.assertEqual(result["extra"], "abc")
        self.assertEqual(result["kw"], "def")

    def test_preserves_function_metadata(self) -> None:
        @requires_valid_run_id
        def my_endpoint(api, run_id):
            """Doc string."""
            return {}

        self.assertEqual(my_endpoint.__name__, "my_endpoint")
        self.assertIn("Doc string", my_endpoint.__doc__ or "")


class SharedRunIdInvariantTests(unittest.TestCase):
    """Issue #427 — l'invariant run_id a UNE seule definition dans `ui`.

    `RUN_ID_RE` vivait dans `cinesort_api`, que `export_support` ne pouvait
    atteindre qu'en import differe (cycle) : ce import differe faisait rougir
    le cliquet `test_lazy_imports_bounded`. L'invariant a ete descendu dans
    `_validators`, atteignable en top-level par tout le paquet.
    """

    def test_run_id_re_does_not_drift_from_the_shared_definition(self) -> None:
        """Ce que cette assertion prouve, exactement.

        `re.compile` MET EN CACHE les motifs identiques : recopier le meme
        motif ailleurs rendrait quand meme `is` vrai. Ce test ne detecte donc
        pas une copie verbatim — il detecte la copie qui a DERIVE, c'est-a-dire
        precisement le risque nomme par #427 (« une copie deriverait le jour ou
        l'invariant bouge »). Une copie verbatim, elle, est sans consequence
        tant qu'elle est verbatim ; c'est sa divergence qui fait le degat, et
        cette divergence casse l'identite de l'objet. Mutation de controle :
        motif recopie avec un caractere de plus -> rouge.
        """
        self.assertIs(cinesort_api.RUN_ID_RE, _validators.RUN_ID_RE)

    def test_both_entry_points_agree_on_every_case(self) -> None:
        """Filet de securite comportemental, independant de l'identite d'objet."""
        for value in ("20260803_141500_123", "ab", "run id!", "a" * 81, "a/b", "--__--"):
            with self.subTest(run_id=value):
                self.assertEqual(
                    bool(cinesort_api.RUN_ID_RE.fullmatch(value)),
                    bool(_validators.RUN_ID_RE.fullmatch(value)),
                )

    def test_export_support_binds_the_validator_at_module_level(self) -> None:
        """Le nom doit etre resolu a l'import du module, pas dans une fonction."""
        self.assertIs(ui_export_support.is_valid_run_id, _validators.is_valid_run_id)

    def test_api_method_delegates_to_the_shared_validator(self) -> None:
        """`CineSortApi._is_valid_run_id` ne doit pas revalider a sa facon.

        `self` n'est pas utilise par la methode : on l'appelle non liee pour
        eviter d'instancier toute l'API.
        """
        cases = ["20260803_141500_123", "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "demo_1", "ab", "run id!", "", None, "a/b"]
        for value in cases:
            with self.subTest(run_id=value):
                self.assertEqual(
                    cinesort_api.CineSortApi._is_valid_run_id(None, value),
                    is_valid_run_id(value),
                )

    def test_normalisation_is_part_of_the_invariant(self) -> None:
        """Les espaces de bord sont manges, le reste est refuse."""
        self.assertTrue(is_valid_run_id("  20260803_141500_123  "))
        self.assertFalse(is_valid_run_id("20260803 141500"))
        self.assertFalse(is_valid_run_id("../../outside"))
        self.assertFalse(is_valid_run_id(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
