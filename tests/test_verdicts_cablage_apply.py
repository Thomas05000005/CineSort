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
from pathlib import Path
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


class _FauxApi:
    """Centre de notifications minimal : enregistre ce qui est publie.

    `leve` permet d'eprouver qu'un centre CASSE ne fait pas echouer un apply
    disque REUSSI — le defaut F11, dans l'autre sens.
    """

    def __init__(self, journal: List[tuple], *, leve: bool = False) -> None:
        self._journal = journal
        self._leve = leve
        self._notify = self

    def notify(self, event_type: str, titre: str, corps: str, level: str = "info") -> None:
        self._journal.append((event_type, titre, corps, level))
        if self._leve:
            raise RuntimeError("centre de notifications indisponible")


class CablageDuVerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.journal: List[tuple[str, str]] = []
        self.notifications: List[tuple] = []
        self.api = _FauxApi(self.notifications)

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
        rows: Any = (),
    ) -> Dict[str, Any]:
        with mock.patch.object(apply_support, "read_apply_audit", return_value=list(evenements or [])):
            return apply_support._avec_verdict(
                payload,
                self.api,
                store=_FauxStore(operations, leve=leve),
                run_paths=_FauxRunPaths(),
                rows=rows,
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
        commun = [{"op_type": "MOVE_FILE", "error_message": "boom"}]
        sain = self._appeler({"apply_batch_id": "b1", "result": {"errors": 1, "moves": 1}}, commun)
        self.assertNotIn("verdict", sain)
        self.journal.clear()
        menteur = self._appeler({"apply_batch_id": "b1", "result": {"errors": 0, "moves": 1}}, commun)
        self.assertIn("verdict", menteur, "le verdict ignore le payload : il ne verifie pas ce qui est affiche")
        inc = menteur["verdict"]["incoherences"][0]
        self.assertEqual(inc["annonce"], {"errors": 0})

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

    def test_le_dry_run_du_CABLAGE_est_bien_celui_de_l_apply(self):
        """Le site d'appel doit transmettre le VRAI `dry_run`, pas une constante.

        Mutant survivant : forcer `dry_run=True` au cablage. Aucun test ne
        rougissait, parce que tous ceux qui attendaient un verdict s'appuyaient
        sur un invariant INSENSIBLE au dry-run (les echecs, l'ampleur, la
        granularite). Seul le controle des COMPTES est derriere ce garde — c'est
        donc lui qu'il faut solliciter ici.
        """
        annonce_muette = {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0}}
        deplacements = [{"op_type": "MOVE_DIR"}, {"op_type": "MOVE_FILE"}]

        reel = self._appeler(dict(annonce_muette), deplacements)
        self.assertIn(
            "deplacements_journalises_non_annonces",
            {i["code"] for i in reel.get("verdict", {}).get("incoherences", [])},
            "premisse : hors dry-run ce cas DOIT lever, sinon le test suivant ne mesure rien",
        )
        self.journal.clear()
        apercu = self._appeler(dict(annonce_muette), deplacements, dry_run=True)
        self.assertNotIn("verdict", apercu, "en apercu, comparer des comptes n'a aucun sens")

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


class LE_CORPS_D_APPLY_APPELLE_VRAIMENT_LE_VERDICT_Tests(unittest.TestCase):
    """Le mutant le plus grave : SUPPRIMER l'appel depuis `_apply_changes_body`.

    Il a d'abord SURVECU. Tous les tests ci-dessus appellent
    `_avec_verdict` en direct : retirer son unique site d'appel ne
    faisait rougir personne. J'aurais eu un module de verdict irreprochable,
    branche sur rien — le risque exact que ce chantier existe pour eviter, et
    que ce depot a deja paye dix fois (10 journaux, ~0 lecteur).

    On execute donc le VRAI `_apply_changes_body` jusqu'a son payload, avec le
    meme patron de harnais que `test_apply_undo_availability_payload.py`.
    """

    def _payload_d_un_apply_reel(self, operations: List[Dict[str, Any]], rows: Any = ()) -> Dict[str, Any]:
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
                list(rows),
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


class LE_CABLAGE_DE_1103_Tests(unittest.TestCase):
    """#1103 traverse-t-il le cablage, ou reste-t-il dans le module pur ?

    L'invariant d'ampleur a besoin de TOUTES les lignes du plan. Si le site
    d'appel ne les lui transmet pas — ou lui transmet les mauvaises — il est
    correct et inutile.
    """

    def _appeler(self, operations, rows):
        from types import SimpleNamespace

        logs = []
        store = _FauxStore(operations)
        with mock.patch.object(apply_support, "read_apply_audit", return_value=[]):
            return (
                apply_support._avec_verdict(
                    {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0, "quarantined": 1}},
                    _FauxApi([]),
                    store=store,
                    run_paths=_FauxRunPaths(),
                    rows=[SimpleNamespace(row_id=r, folder=f) for r, f in rows],
                    dry_run=False,
                    log_fn=lambda n, m: logs.append((n, m)),
                ),
                logs,
            )

    def test_une_quarantaine_de_dossier_PARTAGE_remonte_jusqu_au_payload(self):
        payload, logs = self._appeler(
            [{"op_type": "QUARANTINE_FILE", "src_path": r"D:\films\Saga Rocky"}],
            [("r1", r"D:\films\Saga Rocky"), ("r2", r"D:\films\Saga Rocky")],
        )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertIn(
            "une_operation_emporte_plusieurs_lignes",
            codes,
            "l'invariant #1103 n'est pas cable : les lignes du plan ne lui parviennent pas",
        )

    def test_les_lignes_transmises_sont_bien_CELLES_du_plan(self):
        """Si le site d'appel lisait un autre attribut que `folder`, l'invariant
        recevrait des chemins vides et se tairait pour toujours."""
        payload, _ = self._appeler(
            [{"op_type": "QUARANTINE_FILE", "src_path": r"D:\films\Saga Rocky"}],
            [("r1", r"D:\films\Saga Rocky"), ("r2", r"D:\films\Autre Film")],
        )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertNotIn(
            "une_operation_emporte_plusieurs_lignes",
            codes,
            "deux dossiers DIFFERENTS ne doivent pas passer pour partages",
        )


class LE_CABLAGE_DE_1103_TRAVERSE_T_IL_LE_VRAI_CORPS_Tests(unittest.TestCase):
    """La lacune que la revue adversaire a trouvee, et le test qui la ferme.

    `LE_CABLAGE_DE_1103_Tests` appelle `_avec_verdict` EN DIRECT ; le seul test
    qui executait `_apply_changes_body` lui passait une liste de rows VIDE.
    Consequence mesuree : remplacer `rows=rows` par `rows=()` au site d'appel
    laissait la batterie ENTIERE verte, cliquet compris. L'invariant #1103
    n'etait donc branche par aucune preuve traversant la production.

    C'est la meme lecon que W1 une passe plus tot : tester un helper en direct
    ne dit RIEN de son site d'appel. Ici la lacune etait plus fine — l'appel
    existait, c'est son ARGUMENT qui n'etait jamais eprouve.
    """

    def _corps(self):
        from tests.test_verdicts_cablage_apply import (
            LE_CORPS_D_APPLY_APPELLE_VRAIMENT_LE_VERDICT_Tests as Reel,
        )

        return Reel("test_un_apply_REEL_incoherent_porte_son_verdict")

    def test_les_lignes_du_plan_TRAVERSENT_le_corps_d_apply(self):
        """ROUGE si `rows=rows` devient `rows=()` au site d'appel."""
        from types import SimpleNamespace

        payload = self._corps()._payload_d_un_apply_reel(
            [{"op_type": "QUARANTINE_FILE", "src_path": r"D:\films\Saga Rocky"}],
            rows=[
                SimpleNamespace(row_id="r1", folder=r"D:\films\Saga Rocky"),
                SimpleNamespace(row_id="r2", folder=r"D:\films\Saga Rocky"),
            ],
        )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertIn(
            "une_operation_emporte_plusieurs_lignes",
            codes,
            "le corps d'apply ne transmet pas les lignes du plan a l'invariant #1103",
        )

    def test_un_plan_SAIN_traverse_sans_rien_lever(self):
        """Contre-test : deux dossiers distincts ne doivent pas passer pour
        partages une fois traverse le vrai corps."""
        from types import SimpleNamespace

        payload = self._corps()._payload_d_un_apply_reel(
            [{"op_type": "QUARANTINE_FILE", "src_path": r"D:\films\Saga Rocky"}],
            rows=[
                SimpleNamespace(row_id="r1", folder=r"D:\films\Saga Rocky"),
                SimpleNamespace(row_id="r2", folder=r"D:\films\Autre"),
            ],
        )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertNotIn("une_operation_emporte_plusieurs_lignes", codes)


class LE_CABLAGE_DE_LA_GRANULARITE_Tests(unittest.TestCase):
    """L'invariant de granularite etait branche et TESTE PAR PERSONNE.

    Trois mutants ont survecu a la batterie complete, tous sur ce cablage :
    ne plus l'appeler du tout, ne plus interroger le disque, et transformer une
    destination illisible en accusation. C'est la lecon de W1 pour la troisieme
    fois dans cette campagne — j'avais teste la DECISION et oublie le SITE.

    Ces tests-ci portent sur `_granularites_observees`, la seule E/S de tout le
    controle, et sur le fait que son resultat atteint bien le payload.
    """

    def setUp(self) -> None:
        import shutil
        import tempfile

        self._td = tempfile.mkdtemp(prefix="cinesort_gran_")
        self.racine = Path(self._td)
        self.addCleanup(shutil.rmtree, self._td, ignore_errors=True)

    def test_le_disque_est_REELLEMENT_interroge(self):
        """Un vrai dossier et un vrai fichier, pas une valeur fabriquee."""
        dossier = self.racine / "Saga Rocky"
        dossier.mkdir()
        fichier = self.racine / "rocky.mkv"
        fichier.write_bytes(b"x" * 8)

        observees = apply_support._granularites_observees(
            [
                {"op_type": "QUARANTINE_FILE", "dst_path": str(dossier)},
                {"op_type": "QUARANTINE_FILE", "dst_path": str(fichier)},
            ]
        )
        self.assertEqual([o["dst_est_dossier"] for o in observees], [True, False])

    def test_une_destination_ABSENTE_ne_rend_pas_une_accusation(self):
        """`is_dir()` d'un chemin inexistant rend False — donc pas d'accusation.
        Ce qu'on refuse, c'est d'INVENTER une mesure quand elle est impossible."""
        observees = apply_support._granularites_observees(
            [{"op_type": "QUARANTINE_FILE", "dst_path": str(self.racine / "jamais_creee")}]
        )
        self.assertIs(observees[0]["dst_est_dossier"], False)

    def test_les_op_type_DIR_ne_sont_meme_pas_observes(self):
        """Inutile de toucher le disque pour un type qui ne peut pas mentir dans
        ce sens : on ne paie l'E/S que pour les `*_FILE`."""
        dossier = self.racine / "X"
        dossier.mkdir()
        self.assertEqual(
            apply_support._granularites_observees([{"op_type": "QUARANTINE_DIR", "dst_path": str(dossier)}]),
            [],
        )

    def test_1103_REMONTE_jusqu_au_payload_par_la_granularite(self):
        """ROUGE si l'appel a `verifier_granularite_des_operations` disparait,
        ou si son resultat cesse d'etre ajoute aux incoherences."""
        dossier = self.racine / "Saga Rocky"
        dossier.mkdir()
        journal = []
        with mock.patch.object(apply_support, "read_apply_audit", return_value=[]):
            payload = apply_support._avec_verdict(
                {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0, "quarantined": 1}},
                _FauxApi([]),
                store=_FauxStore([{"op_type": "QUARANTINE_FILE", "dst_path": str(dossier)}]),
                run_paths=_FauxRunPaths(),
                rows=(),
                dry_run=False,
                log_fn=lambda n, m: journal.append((n, m)),
            )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertIn(
            "op_type_fichier_sur_un_dossier",
            codes,
            "la granularite n'est pas cablee : un type FICHIER sur un dossier passe",
        )

    def test_un_vrai_fichier_ne_REMONTE_rien(self):
        """Contre-test : sans lui, accuser systematiquement satisferait le test
        precedent."""
        fichier = self.racine / "rocky.mkv"
        fichier.write_bytes(b"x" * 8)
        with mock.patch.object(apply_support, "read_apply_audit", return_value=[]):
            payload = apply_support._avec_verdict(
                {"ok": True, "apply_batch_id": "b1", "result": {"errors": 0, "quarantined": 1}},
                _FauxApi([]),
                store=_FauxStore([{"op_type": "QUARANTINE_FILE", "dst_path": str(fichier)}]),
                run_paths=_FauxRunPaths(),
                rows=(),
                dry_run=False,
                log_fn=lambda n, m: None,
            )
        codes = {i["code"] for i in payload.get("verdict", {}).get("incoherences", [])}
        self.assertNotIn("op_type_fichier_sur_un_dossier", codes)


class LE_VERDICT_ATTEINT_UN_HUMAIN_Tests(unittest.TestCase):
    """Une cle de payload que personne n'affiche serait un silence de plus.

    C'est MESURE : aucun fichier du front ne lit `verdict`, ni `journal_warning`,
    ni `undo_available`. Le centre de notifications est le seul canal qui survit
    a la fermeture de l'ecran d'apply.
    """

    def _appeler(self, operations, resultat=None, *, notify_casse: bool = False):
        journal: List[tuple] = []
        api = _FauxApi(journal, leve=notify_casse)
        with mock.patch.object(apply_support, "read_apply_audit", return_value=[]):
            payload = apply_support._avec_verdict(
                {"ok": True, "apply_batch_id": "b1", "result": dict(resultat or {"errors": 0})},
                api,
                store=_FauxStore(operations),
                run_paths=_FauxRunPaths(),
                rows=(),
                dry_run=False,
                log_fn=lambda n, m: None,
            )
        return payload, journal

    def test_une_incoherence_est_PUBLIEE(self):
        _, notifications = self._appeler([{"op_type": "MOVE_FILE", "error_message": "boom"}])
        self.assertEqual(len(notifications), 1, f"rien n'a ete publie : {notifications}")
        event_type, titre, corps, niveau = notifications[0]
        self.assertEqual(niveau, "error")
        self.assertNotIn("notifications.", titre, "la cle i18n n'est pas traduite — libelle fantome")
        self.assertIn("b1", corps, "le corps doit nommer le batch, sinon l'alerte est irrattachable")

    def test_un_apply_SAIN_ne_publie_RIEN(self):
        """Contre-test : une alerte a chaque apply apprend a les ignorer.

        Le payload ANNONCE bien le deplacement qu'il a journalise — sans quoi
        l'invariant n3 leverait a juste titre, et ce test ne mesurerait pas ce
        qu'il croit.
        """
        payload, notifications = self._appeler([{"op_type": "MOVE_FILE"}], {"errors": 0, "moves": 1})
        self.assertNotIn("verdict", payload, f"premisse cassee, cet apply n'est pas sain : {payload}")
        self.assertEqual(notifications, [])

    def test_un_centre_de_notifications_CASSE_ne_casse_pas_l_apply(self):
        """L'apply disque a REUSSI : echouer ici serait re-creer F11."""
        payload, _ = self._appeler([{"op_type": "MOVE_FILE", "error_message": "boom"}], notify_casse=True)
        self.assertTrue(payload.get("ok"), "un centre casse a fait echouer un apply reussi")
        self.assertIn("verdict", payload, "le verdict doit rester dans le payload malgre l'echec de publication")


if __name__ == "__main__":
    unittest.main()


class LE_CHEMIN_D_ERREUR_PORTE_AUSSI_SON_VERDICT_Tests(unittest.TestCase):
    """T-PROD-7 : l'apply qui casse APRES avoir deplace ne disait rien de ce qui avait bouge.

    `_avec_verdict` n'avait qu'UN seul site d'appel : le retour nominal.
    L'`except Exception` du meme corps rendait un `_err_response` nu. Or c'est le
    cas le plus grave du produit : trois cents films ont bouge, la finalisation
    casse, et l'utilisateur lit « Echec application » sans apprendre que son
    disque a change ni que l'annulation est disponible.

    Le remede n'a demande AUCUN invariant nouveau. Un `_err_response` ne porte
    aucun compteur d'action disque non nul — c'est exactement la precondition de
    `_verifier_deplacements_tus`, ecrit pour le cas « le journal porte des
    deplacements mais le payload n'en annonce aucun ». L'invariant juste
    existait deja ; il n'etait simplement pas appele la.

    On reutilise le harnais de la classe precedente, en faisant lever
    `_execute_apply` APRES qu'il a pose le `batch_state` : c'est precisement la
    fenetre ou le disque a bouge et ou la finalisation casse.
    """

    def _payload_d_un_apply_QUI_CASSE(self, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        from types import SimpleNamespace

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

        def _execute_puis_casse(*_a: Any, **kwargs: Any) -> Any:
            # Le disque a bouge : le batch existe et porte deja des operations.
            kwargs["batch_state"][0] = "batch-42"
            kwargs["batch_state"][1] = len(operations)
            raise RuntimeError("la finalisation casse APRES les deplacements")

        with (
            mock.patch.object(apply_support, "_validate_apply", return_value=ctx),
            mock.patch.object(apply_support, "_snapshot_jellyfin_watched", return_value=None),
            mock.patch.object(apply_support, "_execute_apply", side_effect=_execute_puis_casse),
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

    def test_le_harnais_atteint_bien_le_chemin_D_ERREUR(self) -> None:
        """Sans ce garde, un harnais qui rendrait un payload NOMINAL ferait
        passer le test suivant sans jamais avoir atteint l'`except`."""
        payload = self._payload_d_un_apply_QUI_CASSE([{"op_type": "MOVE_DIR"}] * 12)
        self.assertFalse(payload.get("ok"), f"le harnais n'atteint pas le chemin d'erreur : {payload}")
        self.assertEqual(payload.get("apply_batch_id"), "batch-42")

    def test_un_apply_qui_casse_APRES_avoir_deplace_porte_son_verdict(self) -> None:
        payload = self._payload_d_un_apply_QUI_CASSE([{"op_type": "MOVE_DIR"}] * 12)
        self.assertIn(
            "verdict",
            payload,
            "l'apply a casse apres avoir deplace 12 dossiers et le payload d'erreur "
            "n'en dit rien : l'utilisateur ignore que son disque a change.",
        )
        self.assertIn(
            "deplacements_journalises_non_annonces",
            [inc["code"] for inc in payload["verdict"]["incoherences"]],
        )

    def test_un_apply_qui_casse_AVANT_tout_deplacement_ne_porte_PAS_de_verdict(self) -> None:
        """Temoin. Sans lui, l'ajout serait indistinguable d'un verdict pose sur
        toutes les erreurs, y compris celles ou rien n'a bouge."""
        payload = self._payload_d_un_apply_QUI_CASSE([])
        self.assertFalse(payload.get("ok"))
        self.assertNotIn("verdict", payload, f"faux positif : {payload.get('verdict')}")
