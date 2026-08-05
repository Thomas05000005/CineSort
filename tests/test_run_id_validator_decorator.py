"""Tests pour le decorateur requires_valid_run_id (issue #101)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

import cinesort.ui.api._validators as _validators
import cinesort.ui.api.cinesort_api as cinesort_api
import cinesort.ui.api.export_support as ui_export_support
from cinesort.domain.i18n_messages import t
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


class RunIdNormaliseEnAvalTests(unittest.TestCase):
    """La valeur VALIDEE doit etre celle qui part en aval.

    Le decorateur validait `str(x or "").strip()` puis appelait la fonction
    avec la valeur BRUTE. Un run_id borde d'espaces etait donc ACCEPTE, puis
    servait a resoudre un run qui n'existe pas.
    """

    def _sonde(self):
        """Fonction decoree qui MEMORISE le run_id qu'elle a reellement recu."""
        recus = []

        @requires_valid_run_id
        def fn(api, run_id, *a, **kw):  # noqa: ARG001
            recus.append(run_id)
            return {"ok": True, "run_id": run_id}

        return fn, recus

    def _api(self):
        api = MagicMock()
        api._is_valid_run_id = staticmethod(is_valid_run_id)
        return api

    def test_positional_recoit_la_valeur_normalisee(self) -> None:
        fn, recus = self._sonde()
        res = fn(self._api(), "  20260803_141500_123  ")
        self.assertTrue(res["ok"])
        self.assertEqual(recus, ["20260803_141500_123"], "la fonction a recu la valeur BRUTE")

    def test_kwarg_recoit_la_valeur_normalisee(self) -> None:
        fn, recus = self._sonde()
        res = fn(self._api(), run_id="  20260803_141500_123  ")
        self.assertTrue(res["ok"])
        self.assertEqual(recus, ["20260803_141500_123"])

    def test_le_meme_run_est_atteint_avec_et_sans_espaces(self) -> None:
        """LE FLUX COMPLET : c'est l'egalite des deux qui compte, pas la forme."""
        fn, recus = self._sonde()
        api = self._api()
        fn(api, "20260803_141500_123")
        fn(api, "  20260803_141500_123  ")
        self.assertEqual(recus[0], recus[1], f"deux appels du meme run divergent : {recus}")

    def test_l_erreur_montre_la_valeur_BRUTE(self) -> None:
        """Un rejet doit dire ce que l'appelant a REELLEMENT envoye.

        Renvoyer une version nettoyee lui ferait chercher un probleme
        introuvable dans une chaine qu'il n'a jamais emise.
        """
        fn, recus = self._sonde()
        res = fn(self._api(), "  pas valide!  ")
        self.assertFalse(res["ok"])
        self.assertEqual(res["run_id"], "  pas valide!  ")
        self.assertEqual(recus, [], "la fonction ne doit pas etre appelee du tout")

    def test_les_autres_arguments_sont_intacts(self) -> None:
        """La reecriture du 1er positionnel ne doit pas decaler les suivants."""
        vus = {}

        @requires_valid_run_id
        def fn(api, run_id, row_id, *, mode="x"):  # noqa: ARG001
            vus.update(run_id=run_id, row_id=row_id, mode=mode)
            return {"ok": True}

        fn(self._api(), "  run_1234  ", "ROW9", mode="strict")
        self.assertEqual(vus, {"run_id": "run_1234", "row_id": "ROW9", "mode": "strict"})


class EndpointsNeRedisentPasLInvariantRunIdTests(unittest.TestCase):
    """Issue #526 — deux endpoints re-testaient `not run_id` derriere le decorateur.

    `probe_support._get_probe_impl` et `quality_report_support.get_quality_report`
    ouvraient sur `if not run_id or not row_id: ...« run_id et row_id sont
    requis »`. Le `not run_id` etait inatteignable — `@requires_valid_run_id` a
    deja repondu `errors.run_invalid_id` pour toute valeur falsy — et le message
    envoyait l'utilisateur verifier un champ qui n'etait jamais en cause.

    Ces tests exercent les endpoints PUBLICS (le chemin d'appel reel des facades),
    pas les corps prives : c'est la seule facon de constater que le decorateur
    tranche avant le corps. `api._is_valid_run_id` est lie au VRAI validateur —
    un `MagicMock` nu rendrait un truthy et fabriquerait le passage qu'on teste.
    """

    def _api(self) -> MagicMock:
        api = MagicMock()
        api._is_valid_run_id = staticmethod(is_valid_run_id)
        return api

    def _appelle_probe(self, api: MagicMock, run_id: Any, row_id: Any) -> dict:
        from cinesort.ui.api import probe_support

        return probe_support.get_probe(api, run_id, row_id, detect_probe_tools_fn=lambda *a, **kw: {})

    def _appelle_quality(self, api: MagicMock, run_id: Any, row_id: Any) -> dict:
        from cinesort.ui.api import quality_report_support

        return quality_report_support.get_quality_report(api, run_id, row_id)

    def test_run_id_vide_est_tranche_par_le_decorateur_pas_par_le_corps(self) -> None:
        """Le corps n'est jamais atteint : c'est ce qui rendait `not run_id` mort."""
        for nom, appel in (("get_probe", self._appelle_probe), ("get_quality_report", self._appelle_quality)):
            for run_id in ("", None, "   "):
                with self.subTest(endpoint=nom, run_id=run_id):
                    api = self._api()
                    res = appel(api, run_id, "row_1")
                    self.assertFalse(res["ok"])
                    self.assertEqual(res["message"], t("errors.run_invalid_id"))
                    # Preuve que le corps n'a pas tourne : sa premiere action
                    # apres la garde est de resoudre le run.
                    api._find_run_row.assert_not_called()

    def test_row_id_manquant_ne_met_plus_en_cause_run_id(self) -> None:
        """Le message doit designer le SEUL champ qui peut encore manquer."""
        attendu = "Identifiant de ligne (row_id) requis."
        for nom, appel in (("get_probe", self._appelle_probe), ("get_quality_report", self._appelle_quality)):
            for row_id in ("", None, "   "):
                with self.subTest(endpoint=nom, row_id=row_id):
                    api = self._api()
                    res = appel(api, "20260803_141500_123", row_id)
                    self.assertFalse(res["ok"])
                    # Texte COMPLET : une assertion par sous-chaine passerait
                    # aussi sur l'ancien message, qui contenait « row_id ».
                    self.assertEqual(res["message"], attendu)
                    self.assertNotIn("run_id", res["message"])
                    api._find_run_row.assert_not_called()

    def test_row_id_valide_laisse_passer_vers_le_corps(self) -> None:
        """La garde ne doit pas se refermer sur un appel legitime.

        Sans ce controle, remplacer la garde par un `return` inconditionnel
        resterait vert : les deux tests precedents n'observent que des rejets.
        """
        for nom, appel in (("get_probe", self._appelle_probe), ("get_quality_report", self._appelle_quality)):
            with self.subTest(endpoint=nom):
                api = self._api()
                api._find_run_row.return_value = None  # -> « Run introuvable », donc le corps a tourne
                res = appel(api, "20260803_141500_123", "row_1")
                self.assertFalse(res["ok"])
                self.assertEqual(res["message"], "Run introuvable.")
                api._find_run_row.assert_called_once_with("20260803_141500_123")


if __name__ == "__main__":
    unittest.main(verbosity=2)
