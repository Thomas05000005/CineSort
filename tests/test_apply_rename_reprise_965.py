"""`renommer_avec_reprise` : la course de #965 ne perd plus un deplacement.

MESURE qui motive ce fichier, sur `main` @ fab0c88f, %TEMP% neuf et vide,
machine au repos, **bras alternes** (seule protection valable : le taux d'echec
derive fortement d'une heure a l'autre) :

    main NU                    : 10 echecs / 20
    main + renommer_avec_reprise:  0 echec  / 20
    Fisher exact bilateral      : p ~ 0,0003

Ce que ces tests verrouillent, et qu'une mesure de taux ne peut pas verrouiller
(elle est statistique, donc inutilisable en CI) :
  - une course qui se resout au 1er palier n'echoue plus ;
  - un verrou PERSISTANT echoue toujours, avec l'exception d'origine ;
  - une erreur qui ne se resoudra jamais en attendant n'est PAS reessayee.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from cinesort.app.apply_core import _REPRISES_RENAME_S, renommer_avec_reprise


def _refus(winerror: int) -> PermissionError:
    exc = PermissionError(13, "Acces refuse")
    exc.winerror = winerror
    return exc


class RenommerAvecRepriseTests(unittest.TestCase):
    def test_une_course_qui_se_resout_ne_perd_plus_le_deplacement(self) -> None:
        """Le cas de #965 : le handle se libere quelques microsecondes trop tard."""
        appels = []

        def _rename(self, cible):  # noqa: ANN001, ARG001
            appels.append(cible)
            if len(appels) == 1:
                raise _refus(5)

        with mock.patch.object(Path, "rename", _rename):
            renommer_avec_reprise(Path("source"), Path("cible"))

        self.assertEqual(len(appels), 2, "le renommage aurait du etre reessaye exactement une fois")

    def test_un_verrou_PERSISTANT_echoue_toujours(self) -> None:
        """La reprise ne doit JAMAIS transformer un vrai verrou en succes."""
        appels = []

        def _rename(self, cible):  # noqa: ANN001, ARG001
            appels.append(cible)
            raise _refus(5)

        with mock.patch.object(Path, "rename", _rename):
            with self.assertRaises(PermissionError) as ctx:
                renommer_avec_reprise(Path("source"), Path("cible"))

        self.assertEqual(ctx.exception.winerror, 5, "l'exception d'origine doit remonter telle quelle")
        self.assertEqual(len(appels), len(_REPRISES_RENAME_S), "tous les paliers doivent avoir ete essayes")

    def test_le_verrou_de_partage_32_est_aussi_repris(self) -> None:
        """WinError 32 (« utilise par un autre processus ») a la meme forme transitoire."""
        appels = []

        def _rename(self, cible):  # noqa: ANN001, ARG001
            appels.append(cible)
            if len(appels) < 3:
                raise _refus(32)

        with mock.patch.object(Path, "rename", _rename):
            renommer_avec_reprise(Path("source"), Path("cible"))

        self.assertEqual(len(appels), 3)

    def test_une_erreur_qui_ne_se_resoudra_pas_n_est_PAS_reessayee(self) -> None:
        """Reessayer un chemin invalide ne ferait que retarder un diagnostic juste."""
        appels = []

        def _rename(self, cible):  # noqa: ANN001, ARG001
            appels.append(cible)
            raise _refus(123)  # ERROR_INVALID_NAME

        with mock.patch.object(Path, "rename", _rename):
            with self.assertRaises(PermissionError):
                renommer_avec_reprise(Path("source"), Path("cible"))

        self.assertEqual(len(appels), 1, "une erreur non transitoire doit remonter au PREMIER essai")

    def test_le_premier_palier_est_immediat(self) -> None:
        """Le chemin nominal ne doit RIEN coster : pas d'attente avant le 1er essai."""
        self.assertEqual(_REPRISES_RENAME_S[0], 0.0)

    def test_le_budget_total_reste_borne(self) -> None:
        """Un dossier reellement verrouille ne doit pas bloquer l'apply longtemps."""
        self.assertLess(sum(_REPRISES_RENAME_S), 0.5, "le budget de reprise doit rester sous la demi-seconde")


class ApplyReelUtiliseLaRepriseTests(unittest.TestCase):
    """Le SITE D'APPEL, pas seulement le helper.

    Sans cette classe, la mutation qui remet `folder.rename(dst)` a la place de
    `renommer_avec_reprise(folder, dst)` laissait les six tests ci-dessus VERTS :
    ils eprouvaient la fonction, jamais son branchement dans `apply`. C'est le
    piege du test vide au site d'appel, deja rencontre trois fois dans ce depot.

    On injecte donc UNE course transitoire — exactement la forme de #965, un
    `WinError 5` qui ne se reproduit pas au second essai — au milieu d'un apply
    REEL, et on verifie que le film est bel et bien deplace.
    """

    def setUp(self) -> None:
        import tempfile

        import cinesort.domain.core as core

        self._tmp = tempfile.mkdtemp(prefix="cinesort_reprise965_")
        self.root = Path(self._tmp) / "Films"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        from tests._helpers import cleanup_test_tree

        cleanup_test_tree(self._tmp)

    def test_un_refus_transitoire_ne_perd_pas_le_deplacement(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi
        from tests._helpers import wait_run_done

        # Le film est DEJA dans un dossier : c'est son RENOMMAGE que #965 perd
        # (`Inception.2010.1080p` -> `Inception (2010)`, la signature exacte de
        # l'issue). Un film nu a la racine est un deplacement de FICHIER, qui
        # passe par un autre chemin et n'aurait rien eprouve ici.
        dossier = self.root / "Inception.2010.1080p"
        dossier.mkdir()
        (dossier / "Inception 2010.mkv").write_bytes(b"x" * 4096)

        api = CineSortApi()
        start = api.run.start_plan({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        wait_run_done(api, run_id)
        rows = api.run.get_plan(run_id).get("rows", [])
        self.assertEqual(len(rows), 1, rows)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in rows
        }

        vrai_rename = Path.rename
        deja_refuse = {"fait": False}

        def _rename_qui_refuse_une_fois(self, cible):  # noqa: ANN001
            # Une seule fois, et seulement sur le dossier du film : refuser
            # d'autres renommages deguiserait le test en autre chose.
            if not deja_refuse["fait"] and "Inception" in str(cible):
                deja_refuse["fait"] = True
                raise _refus(5)
            return vrai_rename(self, cible)

        with mock.patch.object(Path, "rename", _rename_qui_refuse_une_fois):
            payload = api.run.apply(run_id, decisions, False, False)

        self.assertTrue(deja_refuse["fait"], "pre-condition : la course n'a pas ete injectee")
        result = payload.get("result") or {}
        self.assertEqual(int(result.get("errors") or 0), 0, result.get("error_messages"))
        self.assertTrue(
            (self.root / "Inception (2010)" / "Inception 2010.mkv").is_file(),
            "le film n'a pas ete deplace : le site d'appel n'utilise pas la reprise",
        )


if __name__ == "__main__":
    unittest.main()
