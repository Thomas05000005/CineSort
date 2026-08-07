"""Un undo qui n'a RESTAURE AUCUN fichier ne doit pas consommer l'annulation.

Ultra-audit 2026-08. Mesure du defaut, sur un batch dont toutes les operations
sont ignorees (fichier deplace a la main, empreinte modifiee, source disparue) :

    done = 0, skipped = 2, failed = 0
    status  = "UNDONE_DONE"          <- « Undo termine. »
    batch   = clos en UNDONE_DONE    <- sort de get_last_reversible_apply_batch

L'utilisateur lisait donc un succes, ses films n'avaient pas bouge d'un octet, et
son droit a annuler etait consomme. La combinaison des trois est ce qui fait le
degat : chacune prise seule serait recuperable.

CE QUE LE CORRECTIF NE FAIT PAS : il ne fait pas ECHOUER l'undo (`ok` reste
True). Rien n'est casse — il n'y a simplement rien eu a restaurer, et c'est ce
que la reponse doit dire.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from cinesort.ui.api import apply_support


class _StoreEspion:
    """Enregistre les tentatives de cloture du batch, sans rien persister."""

    def __init__(self) -> None:
        self.apply = self
        self.clotures: List[Tuple[str, str]] = []

    def mark_apply_batch_undo_status(self, *, batch_id: str, status: str, **_k: Any) -> None:
        self.clotures.append((str(batch_id), str(status)))

    def close_apply_batch(self, *, batch_id: str, status: str, **_k: Any) -> None:
        self.clotures.append((str(batch_id), str(status)))

    def update_apply_operation_undo_status(self, **_k: Any) -> None:
        return None

    def list_apply_operations(self, **_k: Any) -> list:
        return []

    def list_apply_batches_for_run(self, **_k: Any) -> list:
        return []


class _NotifyEspion:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def notify(self, event_type: str, title: str, body: str, level: str = "info") -> None:
        self.calls.append({"event": event_type, "title": title, "body": body, "level": level})


def _finaliser(
    *,
    done: int,
    skipped: int,
    failed: int,
    store: Optional[_StoreEspion] = None,
    notify: Optional[_NotifyEspion] = None,
) -> Tuple[Dict[str, Any], _StoreEspion, _NotifyEspion]:
    """Execute `_execute_and_finalize_undo` avec des compteurs imposes.

    La panne est injectee au niveau de `_execute_undo_ops` — la fonction qui
    RESSORT ces compteurs en production — et non plus bas : c'est son verdict que
    la finalisation interprete, et c'est cette interpretation qu'on eprouve.
    """
    store = store or _StoreEspion()
    notify = notify or _NotifyEspion()
    api = SimpleNamespace(
        _file_logger=lambda _paths: lambda *_a: None,
        _notify=notify,
        _dispatch_plugin_hook=lambda *a, **k: None,
    )
    compteurs = {
        "done": done,
        "skipped": skipped,
        "failed": failed,
        "conflict_moves": 0,
        "empty_folder_dirs_reversed": 0,
        "cleanup_residual_dirs_reversed": 0,
        "undo_conflicts_root": "",
        "aborted_atomic": False,
        "preverify": {},
    }
    uctx = {
        "batch_id": "b1",
        "irreversible_count": 0,
        "preview_categories": {},
        "empty_bucket": None,
        "residual_bucket": None,
    }
    with (
        mock.patch.object(apply_support, "_execute_undo_ops", return_value=compteurs),
        mock.patch.object(apply_support, "_undo_mkdir_ops", return_value=0),
        mock.patch.object(apply_support, "_write_undo_summary", return_value=None),
    ):
        out = apply_support._execute_and_finalize_undo(
            api,
            "r1",
            uctx,
            [],
            store,
            atomic=False,
            run_paths=SimpleNamespace(run_dir=None),
        )
    return out, store, notify


class UndoSansEffetTests(unittest.TestCase):
    def test_le_batch_n_est_PAS_clos(self) -> None:
        """Le coeur du defaut. `get_last_reversible_apply_batch` filtre
        `status='DONE'` : toute cloture, meme en UNDONE_PARTIAL, retire le batch
        de la liste des annulables."""
        _out, store, _notify = _finaliser(done=0, skipped=2, failed=0)

        self.assertEqual(store.clotures, [], f"l'annulation a ete consommee sans rien restaurer : {store.clotures}")

    def test_le_statut_est_DISTINCT(self) -> None:
        out, _store, _notify = _finaliser(done=0, skipped=2, failed=0)

        self.assertEqual(out.get("status"), "UNDONE_NONE")

    def test_la_reponse_DIT_que_l_annulation_reste_possible(self) -> None:
        """Une donnee de la reponse, pas une deduction que l'UI devrait refaire."""
        out, _store, _notify = _finaliser(done=0, skipped=2, failed=0)

        self.assertIs(out.get("undo_still_available"), True)
        message = str(out.get("message") or "")
        self.assertNotIn("terminé", message.lower(), f"le message annonce un succes : {message!r}")
        self.assertTrue(message.strip())

    def test_la_notification_ne_ressemble_PAS_a_un_succes(self) -> None:
        """« Annulation terminee — 0 restaure, 0 echec » est indistinguable d'un
        succes. La cloche est le seul canal qui survit a la fermeture de l'ecran."""
        _out, _store, notify = _finaliser(done=0, skipped=2, failed=0)

        self.assertEqual(len(notify.calls), 1)
        self.assertEqual(notify.calls[0]["level"], "warning")

    def test_l_undo_n_est_PAS_transforme_en_echec(self) -> None:
        """Garde anti-sur-correction : rien n'est casse, il n'y avait rien a faire."""
        out, _store, _notify = _finaliser(done=0, skipped=2, failed=0)

        self.assertTrue(out.get("ok"))


class ContreEpreuvesTests(unittest.TestCase):
    """Sans elles, un correctif qui ne cloture JAMAIS passerait les tests ci-dessus."""

    def test_un_seul_fichier_restaure_suffit_a_clore(self) -> None:
        out, store, _notify = _finaliser(done=1, skipped=2, failed=0)

        self.assertEqual(out.get("status"), "UNDONE_DONE")
        self.assertEqual(store.clotures, [("b1", "UNDONE_DONE")])
        self.assertIs(out.get("undo_still_available"), False)

    def test_un_echec_reel_reste_UNDONE_PARTIAL_et_clot(self) -> None:
        """`failed > 0` signifie qu'une operation a ete TENTEE — un conflit
        deplace le fichier vers la quarantaine, donc le disque a bouge. Ce cas
        ne doit pas etre confondu avec « rien n'a ete fait »."""
        out, store, _notify = _finaliser(done=0, skipped=0, failed=1)

        self.assertEqual(out.get("status"), "UNDONE_PARTIAL")
        self.assertEqual(store.clotures, [("b1", "UNDONE_PARTIAL")])

    def test_un_batch_VIDE_ne_declenche_pas_le_cas_special(self) -> None:
        """0/0/0 : il n'y avait aucune operation. Comportement historique
        inchange — on ne veut pas rendre annulable a l'infini un batch sans op."""
        out, store, _notify = _finaliser(done=0, skipped=0, failed=0)

        self.assertEqual(out.get("status"), "UNDONE_DONE")
        self.assertEqual(store.clotures, [("b1", "UNDONE_DONE")])


if __name__ == "__main__":
    unittest.main()
