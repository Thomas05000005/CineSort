# -*- coding: utf-8 -*-
"""Contrat : les schemas Pydantic passifs decrivent le payload REELLEMENT produit.

Pourquoi ce test existe
-----------------------
`run_facade` valide six payloads en mode PASSIF (`_validate_passive`). Un echec
n'interrompt rien : il part en `logger.error("[pydantic-passive] ...")`. Trois
de ces six controles etaient structurellement faux, et personne ne pouvait le
voir :

- `start_plan.request` exigeait `settings.library_path`. Cette cle n'est
  produite NULLE PART : la racine vit sous `root` / `roots`
  (`settings_support._migrate_root_to_roots`). Echec **100 %**, a chaque scan.
- `check_duplicates.response` exigeait `run_id`. Le payload est
  `{"ok": True, **find_duplicate_targets(...)}` : il n'y a jamais de `run_id`.
  Echec **100 %**, a chaque ouverture de l'ecran Doublons.
- `apply.response` declarait `applied`, `errors` (liste d'objets), `undo_token`,
  `batch_id`, `dry_run`. Aucune de ces cinq cles n'existe : le payload est
  `{ok, result, apply_batch_id, journal_finalized, undo_available}` et `errors`
  est un **entier** range sous `result`. Comme les cinq champs etaient tous
  optionnels, la validation REUSSISSAIT toujours — en ne verifiant rien, sur
  l'endpoint destructif du depot.

Le seul test qui traversait `start_plan` via la facade ne pouvait pas le voir :
il ajoutait `library_path` A COTE du vrai `root`, avec le commentaire « cle
documentee dans PlanSettings ». Le harnais satisfaisait le schema, la
production non — le piege « le HARNAIS ne reproduisait pas la production »
documente dans `/CLAUDE.md`.

Comment ce test s'en premunit
-----------------------------
Les fixtures sont PRODUITES PAR LE CODE DE PRODUCTION, jamais ecrites a la
main : `plan_support.find_duplicate_targets` pour les doublons,
`core.ApplyResult` pour l'apply, `settings_support._migrate_root_to_roots` pour
les reglages. Et la liste des champs declares est DERIVEE du payload obtenu,
pas recopiee — une recopie derive en silence, c'est exactement ce qui a produit
les trois defauts ci-dessus.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
import cinesort.ui.api.run_flow_support as run_flow_support
import cinesort.ui.api.settings_support as settings_support

try:  # pragma: no cover - pydantic est une dependance de `requirements.txt`
    from cinesort.ui.api.schemas import (
        ApplyResponse,
        CheckDuplicatesResponse,
        StartPlanRequest,
    )

    _PYDANTIC_DISPONIBLE = True
except ImportError:  # pragma: no cover - venv minimal / bundle ampute
    _PYDANTIC_DISPONIBLE = False


# Les cinq noms que `ApplyResponse` declarait et que le payload d'apply ne
# porte PAS. Ils sont nommes ici pour que leur retour fasse rougir ce test.
_CHAMPS_FICTIFS_APPLY = frozenset({"applied", "errors", "undo_token", "batch_id", "dry_run"})


@unittest.skipUnless(_PYDANTIC_DISPONIBLE, "pydantic indisponible dans cet environnement")
class SchemasContreLePayloadReelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="schemas_payload_reel_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Fixtures produites par la PRODUCTION
    # ------------------------------------------------------------------

    def _single(self, row_id: str, folder: Path, source_root: str) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title="Movie",
            proposed_year=2020,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
            source_root=source_root,
        )

    def _payload_check_duplicates(self) -> dict:
        """Payload EXACT de `check_duplicates` sur deux copies de meme identite."""
        cfg = core.Config(root=self.root, enable_collection_folder=True).normalized()
        rows = [
            self._single("r1", self.root / "A" / "Movie (2020)", str(self.root / "A")),
            self._single("r2", self.root / "B" / "Movie (2020)", str(self.root / "B")),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Movie", "year": 2020},
            "r2": {"ok": True, "title": "Movie", "year": 2020},
        }
        data = plan_support.find_duplicate_targets(cfg, rows, decisions)
        # Meme ligne que `run_flow_support.check_duplicates`, meme fonction.
        data["size_savings_total"] = run_flow_support._compute_size_savings_total(data)
        return {"ok": True, **data}

    def _payload_apply(self) -> dict:
        """Payload nominal de `apply_support.apply_changes` (chemin de succes)."""
        resultat = core.ApplyResult()
        return {
            "ok": True,
            "result": resultat.__dict__,
            "apply_batch_id": None,
            "journal_finalized": True,
            "undo_available": False,
        }

    def _reglages_reels(self) -> dict:
        """Reglages tels que la production les pose (jamais ecrits a la main)."""
        reglages = {"root": str(self.root)}
        settings_support._migrate_root_to_roots(reglages)
        return reglages

    # ------------------------------------------------------------------
    # check_duplicates.response
    # ------------------------------------------------------------------

    def test_le_payload_reel_des_doublons_valide_le_schema(self) -> None:
        payload = self._payload_check_duplicates()
        # Pre-condition : sans groupe, le test ne prouverait rien sur `groups`.
        self.assertEqual(payload["total_groups"], 1, f"Fixture invalide : {payload}")
        self.assertEqual(len(payload["groups"][0]["rows"]), 2)
        CheckDuplicatesResponse.model_validate(payload)

    def test_check_duplicates_ne_declare_aucun_champ_absent_du_payload(self) -> None:
        payload = self._payload_check_duplicates()
        declares = set(CheckDuplicatesResponse.model_fields)
        inconnus = declares - set(payload)
        self.assertEqual(
            inconnus,
            set(),
            "CheckDuplicatesResponse declare des cles que le producteur ne pose pas "
            f"({sorted(inconnus)}). C'est ainsi que `run_id` a fait echouer 100 % "
            "des validations. Relever la forme dans find_duplicate_targets.",
        )

    def test_tout_champ_REQUIS_est_present_dans_le_payload_reel(self) -> None:
        """Un requis absent de la charge utile fait echouer 100 % des validations.

        Formulation d'origine : `assertEqual(requis, [])`. Elle attrapait bien le
        defaut vise (`run_id` exige mais jamais pose), mais elle GELAIT le vide :
        elle interdisait a jamais d'exiger meme `ok`, que les DEUX branches du
        producteur posent pourtant systematiquement — `run_flow_support` rend
        `{"ok": True, **data}` en succes et `_err_response` pose `ok: False` en
        echec. Un garde qui interdit de se renforcer n'est plus un garde, c'est un
        plafond.

        La question juste est la SUBORDINATION : tout champ requis doit figurer
        dans la charge utile reelle. Elle attrape exactement le meme defaut et
        laisse le schema se durcir quand la production le permet.
        """
        payload = self._payload_check_duplicates()
        requis = {nom for nom, champ in CheckDuplicatesResponse.model_fields.items() if champ.is_required()}
        absents = sorted(requis - set(payload))
        self.assertEqual(
            absents,
            [],
            f"Champ(s) requis absents du payload reel : {absents}. C'est ainsi que "
            "`run_id` faisait echouer 100 % des validations de check_duplicates.",
        )

    # ------------------------------------------------------------------
    # apply.response
    # ------------------------------------------------------------------

    def test_le_payload_reel_de_lapply_valide_le_schema(self) -> None:
        ApplyResponse.model_validate(self._payload_apply())

    def test_apply_response_ne_declare_plus_les_champs_fictifs(self) -> None:
        declares = set(ApplyResponse.model_fields)
        revenus = _CHAMPS_FICTIFS_APPLY & declares
        self.assertEqual(
            revenus,
            set(),
            f"Champs fictifs revenus dans ApplyResponse : {sorted(revenus)}. "
            "Le payload porte `result` (ApplyResult aplati), `apply_batch_id`, "
            "`journal_finalized` et `undo_available` — et `errors` y est un ENTIER.",
        )
        self.assertIn("result", declares, "`result` est la cle structurante du payload d'apply.")

    def test_les_compteurs_dapply_vivent_bien_sous_result(self) -> None:
        """Derive du dataclass : `errors` est un entier, range sous `result`."""
        payload = self._payload_apply()
        self.assertIn("errors", payload["result"])
        self.assertIsInstance(payload["result"]["errors"], int)
        self.assertNotIn("errors", set(payload) - {"result"})

    # ------------------------------------------------------------------
    # start_plan.request
    # ------------------------------------------------------------------

    def test_les_reglages_reels_valident_startplanrequest(self) -> None:
        reglages = self._reglages_reels()
        self.assertNotIn(
            "library_path",
            reglages,
            "Si la production se met a poser `library_path`, ce test doit etre revu.",
        )
        StartPlanRequest.model_validate({"settings": reglages})

    def test_un_body_minimal_valide_startplanrequest(self) -> None:
        """`_hydrate_settings_from_store` existe parce que le body peut etre minimal.

        Exiger une racine ici recreerait l'echec a 100 % pour ce caller-la.
        """
        StartPlanRequest.model_validate({"settings": {}})


if __name__ == "__main__":
    unittest.main()
