"""Le CABLAGE du verdict dans l'apply, mute a part de la decision.

`tests/test_verdicts_annonce_journal.py` eprouve la DECISION (module pur).
Ici on eprouve le SITE D'APPEL : est-il seulement branche, lit-il les bons
termes, et surtout — que fait-il quand il n'arrive pas a conclure ?

C'est la moitie qu'on oublie. Un module de verdict parfait, appele nulle part ou
appele sur des termes qui ne sont pas ceux affiches a l'utilisateur, ne protege
rien.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest import mock

from cinesort.ui.api import apply_support


class _FauxStore:
    def __init__(self, operations: List[Dict[str, Any]], *, leve: BaseException | None = None) -> None:
        self._ops = operations
        self._leve = leve
        self.apply = self

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        if self._leve is not None:
            raise self._leve
        return list(self._ops)


class _FauxRunPaths:
    run_dir = "run_dir_factice"


class CablageDuVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journal: List[tuple[str, str]] = []

    def _log(self, niveau: str, message: str) -> None:
        self.journal.append((str(niveau), str(message)))

    def _appeler(
        self,
        payload: Dict[str, Any],
        operations: List[Dict[str, Any]],
        evenements: List[Dict[str, Any]] | None = None,
        *,
        dry_run: bool = False,
        leve: BaseException | None = None,
    ) -> Dict[str, Any]:
        with mock.patch.object(apply_support, "read_apply_audit", return_value=list(evenements or [])):
            return apply_support._payload_avec_verdict(
                payload,
                store=_FauxStore(operations, leve=leve),
                run_paths=_FauxRunPaths(),
                dry_run=dry_run,
                log_fn=self._log,
            )

    def _warns(self) -> List[str]:
        return [m for niveau, m in self.journal if niveau == "WARN"]

    # --- le cablage est-il VIVANT ? -------------------------------------
    def test_1062_de_bout_en_bout_le_payload_PORTE_l_incoherence(self):
        """Le cas reel : `errors: 0` annonce, des echecs inscrits au journal."""
        payload = self._appeler(
            {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0, "quarantined": 0}},
            [{"op_type": "MOVE_FILE", "error_message": "PermissionError"}],
        )
        self.assertIn("verdict", payload, "l'incoherence n'a pas atteint le payload")
        self.assertIn(
            "succes_annonce_malgre_des_echecs",
            {i["code"] for i in payload["verdict"]["incoherences"]},
        )

    def test_l_incoherence_part_AUSSI_dans_le_journal_technique(self):
        """Un champ de payload que personne n'affiche serait un silence de plus.
        Le WARN est le canal que je peux relire apres coup."""
        self._appeler(
            {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0}},
            [{"op_type": "MOVE_FILE", "error_message": "boom"}],
        )
        warns = [m for m in self._warns() if "INCOHERENCE" in m]
        self.assertEqual(len(warns), 1, f"un WARN attendu, vu : {self._warns()}")
        self.assertIn("b1", warns[0], "le WARN doit nommer le batch, sinon il est irrattachable")
        self.assertIn("operations_en_echec", warns[0], "le WARN doit porter les TERMES, pas juste la conclusion")

    def test_un_apply_SAIN_n_ajoute_rien_au_payload(self):
        """Contre-test : une cle `verdict` sur chaque apply normal ferait
        desapprendre a la lire, et les vraies avec."""
        payload = self._appeler(
            {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0, "quarantined": 1, "renames": 0, "moves": 0}},
            [{"op_type": "QUARANTINE_FILE"}],
        )
        self.assertNotIn("verdict", payload)
        self.assertEqual(self._warns(), [])

    # --- les termes lus sont-ils CEUX de l'utilisateur ? ------------------
    def test_les_termes_viennent_du_PAYLOAD_pas_d_ailleurs(self):
        """Si le controle lisait une autre source que le payload rendu, il
        validerait autre chose que ce qui est affiche — le defaut meme qu'il est
        cense attraper. On altere le payload et le verdict doit suivre."""
        commun = [{"op_type": "QUARANTINE_FILE"}]
        sain = self._appeler({"apply_batch_id": "b1", "result": {"quarantined": 1}}, commun)
        self.assertNotIn("verdict", sain)
        self.journal.clear()
        menteur = self._appeler({"apply_batch_id": "b1", "result": {"quarantined": 9}}, commun)
        self.assertIn("verdict", menteur, "le verdict ignore le payload : il ne verifie pas ce qui est affiche")
        inc = menteur["verdict"]["incoherences"][0]
        self.assertEqual(inc["annonce"], {"quarantined": 9})

    def test_les_EVENEMENTS_d_audit_comptent_aussi(self):
        """La seconde source. Sans elle, l'apply le plus courant — des echecs
        jamais inscrits en base — passerait pour coherent."""
        payload = self._appeler(
            {"apply_batch_id": "b1", "result": {"errors": 0, "quarantined": 0}},
            [],
            [{"event": "error", "context": "move", "message": "PermissionError"}],
        )
        self.assertIn("verdict", payload)

    # --- que fait-il quand il n'arrive PAS a conclure ? -------------------
    def test_un_journal_ILLISIBLE_ne_passe_pas_pour_un_apply_verifie(self):
        """Le point qui compte le plus. Un controle qui echoue en silence rend
        un apply non verifie indistinguable d'un apply verifie — un echec
        transforme en succes silencieux, exactement ce qu'on combat."""
        import sqlite3

        payload = self._appeler(
            {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0}},
            [],
            leve=sqlite3.OperationalError("database is locked"),
        )
        self.assertNotIn("verdict", payload, "aucun verdict ne doit etre invente")
        warns = [m for m in self._warns() if "NON CALCULE" in m]
        self.assertEqual(len(warns), 1, f"le non-calcul doit etre DIT, vu : {self._warns()}")
        self.assertIn("database is locked", warns[0], "la raison doit etre lisible sans rejouer l'apply")

    def test_un_journal_illisible_ne_CASSE_pas_l_apply(self):
        """L'autre bord : l'apply disque a REUSSI. Faire echouer la reponse a
        cause du controle serait re-creer le defaut F11."""
        payload = self._appeler(
            {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0}},
            [],
            leve=RuntimeError("boom"),
        )
        self.assertTrue(payload.get("ok"), "l'apply reussi doit rester reussi")

    def test_le_DRY_RUN_ne_lit_meme_pas_le_journal(self):
        """En apercu `apply_batch_id` est None : il n'y a rien a lire, et le
        verdict ne doit rien inventer."""
        payload = self._appeler(
            {"ok": True, "apply_batch_id": None, "result": {"quarantined": 4, "renames": 9, "errors": 0}},
            [],
            dry_run=True,
        )
        self.assertNotIn("verdict", payload)
        self.assertEqual(self._warns(), [])


if __name__ == "__main__":
    unittest.main()


class LE_CORPS_D_APPLY_APPELLE_VRAIMENT_LE_VERDICT_Tests(unittest.TestCase):
    """Le mutant le plus grave : SUPPRIMER l'appel depuis `_apply_changes_body`.

    Il a d'abord SURVECU. Tous les tests ci-dessus appellent
    `_payload_avec_verdict` en direct : retirer son unique site d'appel ne
    faisait rougir personne. J'aurais eu un module de verdict irreprochable,
    branche sur rien — le risque exact que ce chantier existe pour eviter, et
    que ce depot a deja paye dix fois (10 journaux, ~0 lecteur).

    On execute donc le VRAI `_apply_changes_body` jusqu'a son payload, avec le
    meme patron de harnais que `test_apply_undo_availability_payload.py`.
    """

    def _payload_d_un_apply_reel(self, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        from types import SimpleNamespace

        from cinesort.domain import core as core_mod

        logs: List[tuple[str, str]] = []
        store = _FauxStore(operations)
        store.backup_now = lambda *, trigger: None  # type: ignore[attr-defined]
        store.close_apply_batch = lambda **kwargs: None  # type: ignore[attr-defined]
        api = SimpleNamespace(
            _get_run=lambda _run_id: None,
            _app_version="test",
            _notify=SimpleNamespace(notify=lambda *a, **k: None),
            _dispatch_plugin_hook=lambda *a, **k: None,
            _dispatch_email=lambda *a, **k: None,
            log_api_exception=lambda *a, **k: None,
        )
        ctx = {
            "ok": True,
            "_ctx": (
                SimpleNamespace(),
                SimpleNamespace(run_dir="run_dir_factice"),
                [],
                lambda niveau, message: logs.append((str(niveau), str(message))),
                store,
                {},
                set(),
            ),
        }

        def _fake_execute(*_a: Any, **kwargs: Any) -> Any:
            kwargs["batch_state"][0] = "batch-42"
            kwargs["batch_state"][1] = 1
            return (core_mod.ApplyResult(applied_count=1, considered_rows=1), "batch-42", 1)

        with (
            mock.patch.object(apply_support, "_validate_apply", return_value=ctx),
            mock.patch.object(apply_support, "_snapshot_jellyfin_watched", return_value=None),
            mock.patch.object(apply_support, "_execute_apply", side_effect=_fake_execute),
            mock.patch.object(apply_support, "_summarize_apply", return_value=None),
            mock.patch.object(apply_support, "_trigger_jellyfin_refresh", return_value=None),
            mock.patch.object(apply_support, "_trigger_plex_refresh", return_value=None),
            mock.patch.object(apply_support, "read_apply_audit", return_value=[]),
        ):
            payload = apply_support._apply_changes_body(
                api,
                "run-1",
                {},
                False,
                False,
                cleanup_scope_label=lambda value: str(value),
                cleanup_status_label=lambda *a, **k: "",
                cleanup_reason_label=lambda value: str(value),
            )
        self._logs = logs
        return payload

    def test_le_harnais_produit_bien_un_apply_NOMINAL(self):
        """Sans ce garde, un harnais casse rendrait un payload d'erreur et le
        test suivant serait vert sans jamais avoir atteint le verdict."""
        payload = self._payload_d_un_apply_reel([{"op_type": "MOVE_FILE"}])
        self.assertTrue(payload.get("ok"), f"le harnais n'atteint pas l'apply nominal : {payload}")
        self.assertEqual(payload.get("apply_batch_id"), "batch-42")

    def test_un_apply_REEL_incoherent_porte_son_verdict(self):
        """ROUGE si l'appel disparait de `_apply_changes_body`."""
        payload = self._payload_d_un_apply_reel(
            [{"op_type": "MOVE_FILE", "error_message": "PermissionError"}],
        )
        self.assertIn(
            "verdict",
            payload,
            "le corps d'apply n'appelle plus le verdict : le module est branche sur rien",
        )
        self.assertFalse(payload["verdict"]["coherent"])

    def test_un_apply_REEL_coherent_ne_porte_PAS_de_verdict(self):
        payload = self._payload_d_un_apply_reel([{"op_type": "MOVE_FILE"}])
        self.assertNotIn("verdict", payload)
