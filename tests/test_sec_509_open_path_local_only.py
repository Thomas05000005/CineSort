"""Issue #509 — `open_path` refuse les requetes REST distantes.

`history_support.open_path` finit par `os.startfile()` sur la machine qui
HEBERGE CineSort. Ses deux voisins immediats (`open_logs_folder`,
`open_external_url`) refusent deja les callers REST distants ; `open_path` ne
le faisait pas. Les protections existantes (refus des symlinks, confinement
dans `state_dir` + `root`) valident le CHEMIN, jamais l'ORIGINE de l'appel.

Portee, dite honnetement : `open_path` n'est pas atteignable via REST, car
`rest_server._EXCLUDED_METHODS` l'exclut du dispatcher. Le garde est donc de la
defense en profondeur. Il n'est pas decoratif pour autant : `open_logs_folder` a
justement ete RETIREE de cette liste (V2-09) pour debloquer un bouton du
dashboard, et c'est son garde local-only qui a rattrape l'exposition.

D'ou les deux familles de tests ci-dessous : le garde lui-meme, ET l'exclusion
du dispatcher, verifiee sur le dispatcher REELLEMENT construit.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra import rest_server
from cinesort.infra.log_context import reset_remote_request, set_remote_request


class OpenPathLocalOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_open_path_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True)
        self.target = self.state_dir / "un_dossier"
        self.target.mkdir()
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def test_appel_rest_distant_refuse_sans_toucher_lexplorateur(self) -> None:
        """ROUGE sans le correctif : l'appel traversait jusqu'a os.startfile."""
        appels: list = []

        def _spy(*args: object, **_kw: object) -> dict:
            appels.append(args)
            return {"ok": True, "_atteint": True}

        token = set_remote_request(True)
        try:
            with mock.patch.object(backend.history_support, "open_path", side_effect=_spy):
                result = self.api.open_path(str(self.target))
        finally:
            reset_remote_request(token)

        self.assertFalse(result["ok"], "un refus ne doit jamais ressembler a un succes")
        self.assertIn("locale", str(result.get("message", "")).lower())
        self.assertEqual(
            appels,
            [],
            "l'implementation ne doit meme pas etre atteinte : c'est elle qui appelle os.startfile",
        )

    def test_appel_local_toujours_delegue(self) -> None:
        """Controle positif : le garde ne doit rien casser en local.

        Sans ce test, un `open_path` qui refuserait TOUT rendrait le test
        precedent vert sans rien prouver.
        """
        appels: list = []
        with mock.patch.object(
            backend.history_support, "open_path", side_effect=lambda *a, **k: appels.append(a) or {"ok": True}
        ):
            result = self.api.open_path(str(self.target))

        self.assertTrue(result["ok"])
        self.assertEqual(len(appels), 1, "en local, la delegation doit avoir lieu normalement")

    def test_le_flag_distant_est_faux_par_defaut(self) -> None:
        """Le bridge pywebview natif et le dashboard sur 127.0.0.1 ne sont pas
        affectes : `is_remote_request()` ne vaut True que pour une IP non
        loopback vue par le dispatcher REST."""
        appels: list = []
        with mock.patch.object(
            backend.history_support, "open_path", side_effect=lambda *a, **k: appels.append(a) or {"ok": True}
        ):
            self.api.open_path(str(self.target))
        self.assertEqual(len(appels), 1)


class OpenPathNotReachableOverRestTests(unittest.TestCase):
    """Verrouille la premiere barriere : l'exclusion du dispatcher.

    Verifie sur le dispatcher REELLEMENT construit a partir de l'API, pas par
    lecture de la liste de constantes : c'est la table de routage qui compte.
    """

    def _routes(self, *, legacy_pass1: bool) -> dict:
        env = {"CINESORT_REST_LEGACY_PASS1_ENABLED": "1"} if legacy_pass1 else {}
        with mock.patch.dict(os.environ, env, clear=False):
            return rest_server._get_api_methods(backend.CineSortApi())

    def test_aucune_route_rest_ne_mene_a_open_path(self) -> None:
        for legacy in (False, True):
            with self.subTest(legacy_pass1=legacy):
                routes = self._routes(legacy_pass1=legacy)
                self.assertTrue(routes, "dispatcher vide : le test ne prouverait rien")
                fautives = [name for name in routes if "open_path" in name]
                self.assertEqual(fautives, [], f"open_path expose via REST : {fautives!r}")

    def test_les_voisins_locaux_restent_exposes_et_gardes(self) -> None:
        """Controle positif : le dispatcher expose bien d'autres methodes
        `open_*`, donc l'absence de `open_path` n'est pas un artefact d'un
        dispatcher casse."""
        routes = self._routes(legacy_pass1=False)
        self.assertIn("runtime/open_logs_folder", routes)
        self.assertIn("runtime/open_external_url", routes)


if __name__ == "__main__":
    unittest.main()
