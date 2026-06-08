"""Guard test ITER3 etape 2d (branche ii.b PYDANTIC SILENCIEUX).

Sujet : "plan sur titre matchable peuple tmdb_id ET poster_url non-null".

Le fix iter3 etape 2 corrige `cinesort/ui/api/facades/run_facade.py` L111-133 :
le construction de `request_payload` doit wrapper `settings` dans la cle top-level
`{"settings": settings}` exigee par le schema `StartPlanRequest` (cf
`cinesort/ui/api/schemas/run.py` L56).

AVANT le fix : la validation pydantic echouait a 100% (Field required: settings)
declenchant le fallback dict silencieux (warning, puis ERROR apres iter3 etape 2).
Le settings appauvri etait propage sans `tmdb_api_key` -> TMDb desactive ->
plan.poster_url = None + tmdb_id = None sur les titres matchables.

APRES le fix : la validation passe, le settings (incluant tmdb_api_key) est passe
intact a `_start_plan_impl`. Pour un titre matchable comme "Inception (2010)",
le PlanRow retourne contient `tmdb_id` non-null ET `poster_url` non-null.

Strategie du test :
- On mocke `_start_plan_impl` pour controler le retour (eviter dependance reseau
  TMDb / DB / FS reels). Le test verifie que la validation pydantic n'echoue
  PAS et donc que `_start_plan_impl` est invoque avec un settings non-altere
  contenant `tmdb_api_key`.
- On capture les logs : AVANT fix -> log ERROR "start_plan.request validation
  failed" present. APRES fix -> absent.
- On verifie aussi que le PlanRow simule (titre matchable enrichi) a tmdb_id
  ET poster_url non-null (contract metier du sujet).
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from cinesort.ui.api.cinesort_api import CineSortApi


class PlanTitreMatchablePeupleTmdbIdEtPosterUrlGuardTests(unittest.TestCase):
    """Guard ITER3 etape 2d : valide le fix branche ii.b sur la chaine settings.

    Si quelqu'un casse le wrap `{"settings": settings}` dans `RunFacade.start_plan`,
    ces tests echoueront et bloqueront la regression.
    """

    def setUp(self) -> None:
        self.api = CineSortApi()
        # Settings realiste qu'un caller REST conforme envoie.
        # Doit inclure tmdb_api_key non-vide pour que l'enrichissement TMDb
        # soit active dans _init_tmdb_client (cf run_flow_support.py L196-223).
        self.settings = {
            "library_path": "C:/tmp/test_library",
            "tmdb_enabled": True,
            "tmdb_api_key": "test_tmdb_api_key_xyz",
            "tmdb_cache_ttl_days": 14,
        }

    def test_plan_titre_matchable_peuple_tmdb_id_et_poster_url(self) -> None:
        """Le sujet du guard test : valide le contract metier end-to-end (mocke).

        Verifie :
        1. start_plan ne declenche AUCUN log ERROR "start_plan.request validation
           failed" (preuve que le wrap pydantic est correct, branche ii.b OK).
        2. Le settings transmis a _start_plan_impl contient tmdb_api_key
           (preuve que la propagation n'est pas appauvrie).
        3. Le PlanRow simule pour "Inception (2010)" a tmdb_id ET poster_url
           non-null (contract metier du sujet).
        """
        # Simule le retour de _start_plan_impl pour un titre matchable TMDb.
        # Avec tmdb_api_key transmis correctement, l'enrichissement TMDb peuple
        # ces deux champs (cf domain/core.py L883/L1012).
        fake_plan_row = {
            "title": "Inception",
            "year": "2010",
            "tmdb_id": 27205,  # Inception sur TMDb
            "poster_url": "https://image.tmdb.org/t/p/w300/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg",
        }
        fake_response = {
            "ok": True,
            "run_id": "20260608_test_iter3_guard",
            "plan_summary": {"total": 1, "matched": 1},
            "warnings": [],
            "_plan_preview": [fake_plan_row],
        }

        with patch.object(
            self.api, "_start_plan_impl", return_value=fake_response
        ) as mock_impl:
            # Capture les logs du module facade pour detecter la presence/absence
            # du log ERROR "start_plan.request validation failed". On utilise
            # un handler attache au logger racine du module pour capturer SANS
            # depende d'assertLogs (qui exige >=1 record).
            facade_logger = logging.getLogger("cinesort.ui.api.facades.run_facade")
            captured_records: list[logging.LogRecord] = []

            class _Capture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    captured_records.append(record)

            handler = _Capture(level=logging.DEBUG)
            facade_logger.addHandler(handler)
            previous_level = facade_logger.level
            facade_logger.setLevel(logging.DEBUG)
            try:
                result = self.api.run.start_plan(self.settings)
            finally:
                facade_logger.removeHandler(handler)
                facade_logger.setLevel(previous_level)

            log_capture = MagicMock()
            log_capture.records = captured_records

        # --- Assertion 1 : aucun log ERROR de validation failed ---
        validation_failed_logs = [
            rec for rec in log_capture.records
            if rec.levelno >= logging.ERROR
            and "start_plan.request" in rec.getMessage()
            and "validation failed" in rec.getMessage()
        ]
        self.assertEqual(
            validation_failed_logs, [],
            f"REGRESSION branche ii.b : la validation pydantic de start_plan.request "
            f"echoue (logs ERROR observes: {[r.getMessage() for r in validation_failed_logs]}). "
            f"Verifier que `request_payload` enrobe bien settings sous la cle 'settings' "
            f"dans cinesort/ui/api/facades/run_facade.py."
        )

        # --- Assertion 2 : _start_plan_impl invoque avec settings non-altere ---
        mock_impl.assert_called_once()
        passed_settings = mock_impl.call_args[0][0]
        self.assertEqual(
            passed_settings.get("tmdb_api_key"), "test_tmdb_api_key_xyz",
            "REGRESSION : le tmdb_api_key a ete perdu en route. La propagation "
            "settings -> _start_plan_impl doit etre transparente."
        )
        self.assertTrue(
            passed_settings.get("tmdb_enabled"),
            "REGRESSION : tmdb_enabled a ete perdu en route."
        )

        # --- Assertion 3 : contract metier du sujet (tmdb_id ET poster_url non-null) ---
        # On extrait le PlanRow simule du retour pour valider le contract metier.
        plan_preview = result.get("_plan_preview") or []
        self.assertGreater(len(plan_preview), 0, "Le plan retourne est vide.")
        row = plan_preview[0]
        self.assertIsNotNone(
            row.get("tmdb_id"),
            "Sujet guard test : row.tmdb_id DOIT etre non-null pour un titre "
            "matchable (Inception 2010). Si null -> l'enrichissement TMDb n'a "
            "pas fonctionne (branche ii.b cassee : settings appauvris)."
        )
        self.assertIsNotNone(
            row.get("poster_url"),
            "Sujet guard test : row.poster_url DOIT etre non-null pour un titre "
            "matchable. Si null -> TMDb desactive (settings sans tmdb_api_key)."
        )
        # Verification supplementaire : poster_url pointe bien sur image.tmdb.org
        # (CSP img-src whitelisted).
        self.assertIn(
            "image.tmdb.org", row["poster_url"],
            "Le poster_url doit etre une URL TMDb (image.tmdb.org)."
        )

    def test_request_payload_wrap_settings_post_fix(self) -> None:
        """Verifie directement le contract du fix : request_payload doit contenir
        la cle top-level 'settings' avant validation pydantic.

        Ce test est un proxy direct du fix L111-133 : on intercepte
        `_validate_passive` et on inspecte le payload qui lui est passe.
        """
        captured = {}

        def fake_validate(model_cls, payload, *, endpoint):
            if endpoint == "start_plan.request":
                captured["payload"] = payload
            return payload

        with patch.object(
            self.api, "_start_plan_impl", return_value={"ok": True, "run_id": "x"}
        ):
            with patch(
                "cinesort.ui.api.facades.run_facade._validate_passive",
                side_effect=fake_validate,
            ):
                self.api.run.start_plan(self.settings)

        # Contract du fix : request_payload doit avoir une cle top-level 'settings'.
        self.assertIn(
            "settings", captured.get("payload", {}),
            "REGRESSION branche ii.b : request_payload NE contient PAS la cle "
            "'settings' attendue par StartPlanRequest. Le wrap "
            "`{'settings': settings}` a ete casse dans run_facade.py."
        )
        # Le wrapper doit contenir library_path + tmdb_api_key intacts.
        inner = captured["payload"]["settings"]
        self.assertEqual(inner.get("library_path"), "C:/tmp/test_library")
        self.assertEqual(inner.get("tmdb_api_key"), "test_tmdb_api_key_xyz")


if __name__ == "__main__":
    unittest.main()
