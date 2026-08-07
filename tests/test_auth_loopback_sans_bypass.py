"""Une requete locale sans jeton valide ne doit plus rien obtenir.

De 2026-06-08 au 2026-08-07, `_check_auth` rendait `True` sans verifier le jeton
des que le client etait en loopback et le bind en `127.0.0.1`. Tout processus
capable d'ouvrir une socket locale — extension de navigateur, script, tache
planifiee, **ou une autre session utilisateur de la meme machine** — pouvait
donc appeler les 172 methodes de facade exposees en POST, dont 20 destructives
(`settings.reset_database`, `settings.reset_settings`, `run.delete_run`...).

POURQUOI IL A ETE RETIRE. Sa justification ecrite invoquait une « mutation
invisible du token » (BOM U+FEFF, percent-decode, normalisation unicode). C'etait
un symptome : la cause reelle des 401 etait que `get_settings()` MASQUAIT le
jeton en huit puces U+2022 avant qu'il n'entre dans l'URL. Corrigee le
2026-06-07 — soit la VEILLE de l'ajout du bypass.

MESURES DU RETRAIT (2026-08-07) :
  - aller-retour `?ntoken=` sur 20 000 jetons `token_urlsafe(24)` : 0 corruption
    (`quote()` est un no-op sur cet alphabet, et le jeton est chiffre au repos
    par DPAPI donc hors d'atteinte d'un BOM de `settings.json`) ;
  - navigateur reel, bypass coupe : 15 appels API tous en 200, jeton persiste a
    l'octet pres en `localStorage`, rechargement SANS `?ntoken=` fonctionnel.

CE QUE CE FICHIER GARDE. La configuration exacte ou l'ancien bypass accordait
l'acces : client loopback, bind `127.0.0.1`, kill-switch ABSENT. Les tests
d'authentification existants posaient `CINESORT_DISABLE_LOCAL_AUTH=1` pour
pouvoir observer quoi que ce soit — ils ne pouvaient donc PAS detecter une
reintroduction du bypass. Ceux d'ici ne posent rien.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import unittest
from http.client import HTTPConnection

from cinesort.infra.rest_server import RestApiServer
from cinesort.ui.api.cinesort_api import CineSortApi

_TOKEN = "JETON-DE-TEST-PAS-UN-SECRET"


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ServeurLocalMixin:
    """Demarre un REST sur un etat jetable, et REND L'ENVIRONNEMENT INTACT.

    `LOCALAPPDATA` doit imperativement etre restaure. Une premiere version de ce
    fichier le posait sans le remettre : Playwright y resout le chemin de son
    navigateur (`%LOCALAPPDATA%/ms-playwright`), et tous les tests `[chromium]`
    executes ENSUITE allaient chercher Chromium dans un repertoire temporaire
    deja supprime — **52 `ERROR at setup`** en batterie complete, pour un fichier
    qui passait parfaitement seul.

    Cette famille d'echec n'apparait PAS dans un grep `FAILED` (ce sont des
    `ERROR at setup`), et « rejouer en isolation » la rend invisible : c'est le
    voisinage qui la revele.

    La restauration est en `finally` : si `server.stop()` leve, l'environnement
    doit quand meme etre rendu.
    """

    _prefixe = "cinesort_auth_"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix=cls._prefixe)
        cls._env_precedent = {
            "CINESORT_DISABLE_LOCAL_AUTH": os.environ.pop("CINESORT_DISABLE_LOCAL_AUTH", None),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA"),
        }
        os.environ["LOCALAPPDATA"] = cls._tmp
        cls.server = None
        # `unittest` n'appelle `tearDownClass` QUE si `setUpClass` s'est terminee
        # sans exception. Sans ce `try`, une levee de `CineSortApi()`, de
        # `_port_libre()` (le port est rendu apres fermeture de la socket : un
        # autre processus peut le prendre entre-temps) ou de `start()` laisserait
        # `LOCALAPPDATA` pointe sur un repertoire que le nettoyage supprime
        # ensuite — et les 52 `ERROR at setup` de Playwright reviendraient par ce
        # chemin d'exception. C'est exactement la panne decrite plus haut,
        # reouverte par la porte de derriere.
        try:
            cls.api = CineSortApi()
            cls.port = _port_libre()
            cls.server = RestApiServer(cls.api, port=cls.port, token=_TOKEN)
            cls.server.start()
        except BaseException:
            cls._rendre_l_environnement()
            raise

    @classmethod
    def _rendre_l_environnement(cls) -> None:
        for nom, valeur in getattr(cls, "_env_precedent", {}).items():
            if valeur is None:
                os.environ.pop(nom, None)
            else:
                os.environ[nom] = valeur
        shutil.rmtree(getattr(cls, "_tmp", ""), ignore_errors=True)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            if cls.server is not None:
                cls.server.stop()
        finally:
            cls._rendre_l_environnement()

    def _poster(self, route: str, jeton: str | None) -> tuple[int, dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        entetes = {"Content-Type": "application/json"}
        if jeton is not None:
            entetes["Authorization"] = f"Bearer {jeton}"
        conn.request("POST", route, body=b"{}", headers=entetes)
        resp = conn.getresponse()
        code = resp.status
        brut = resp.read()
        conn.close()
        try:
            return code, json.loads(brut or b"{}")
        except (ValueError, TypeError):
            return code, {}


class LoopbackNEstPlusUneExemptionTests(_ServeurLocalMixin, unittest.TestCase):
    """Aucun `CINESORT_DISABLE_LOCAL_AUTH` n'est pose ici : c'est le point.

    Poser le kill-switch reviendrait a mesurer un chemin que la production ne
    prend pas, et laisserait un retour du bypass parfaitement invisible.
    """

    _prefixe = "cinesort_auth_bypass_"

    def test_le_serveur_est_bien_dans_la_configuration_DU_BYPASS(self) -> None:
        """Sans cette verification, tous les tests de cette classe pourraient
        passer pour la mauvaise raison.

        L'ancien bypass exigeait `bind_host == "127.0.0.1"` ET un client
        loopback. Si le serveur d'essai se liait sur `0.0.0.0`, l'auth
        s'appliquerait de toute facon et les 401 ci-dessous ne prouveraient
        rien du RETRAIT — ils prouveraient qu'on a teste ailleurs.
        """
        self.assertEqual(self.server.host, "127.0.0.1", "le serveur d'essai n'est pas dans la configuration du bypass")
        self.assertIsNone(
            os.environ.get("CINESORT_DISABLE_LOCAL_AUTH"),
            "le kill-switch est pose : on mesurerait un chemin que la production ne prend pas",
        )

    def test_sans_jeton_depuis_LOOPBACK_le_serveur_refuse(self) -> None:
        """Le coeur du retrait. Avant, cette requete rendait 200."""
        code, corps = self._poster("/api/settings/get_settings", None)

        self.assertEqual(
            code,
            401,
            "un POST local SANS jeton est servi : le bypass d'auth loopback est de retour",
        )
        self.assertFalse(corps.get("ok", True))

    def test_avec_un_MAUVAIS_jeton_depuis_loopback_le_serveur_refuse(self) -> None:
        code, _ = self._poster("/api/settings/get_settings", "pas-le-bon-jeton")

        self.assertEqual(code, 401, "un mauvais jeton est accepte en loopback")

    def test_une_methode_DESTRUCTIVE_n_est_pas_atteignable_sans_jeton(self) -> None:
        """Ce que le bypass exposait vraiment : la reinitialisation de la base.

        On vise `settings/reset_database` — le refus doit intervenir a l'AUTH,
        donc avant que la moindre ligne ne soit touchee.
        """
        code, corps = self._poster("/api/settings/reset_database", None)

        self.assertEqual(code, 401, "reset_database est atteignable sans jeton depuis un processus local")
        self.assertFalse(corps.get("ok", True))

    def test_le_BON_jeton_passe_toujours(self) -> None:
        """Contre-epreuve indispensable : sans elle, un serveur qui refuse TOUT
        passerait les trois tests ci-dessus."""
        code, corps = self._poster("/api/settings/get_settings", _TOKEN)

        self.assertEqual(code, 200, "le jeton valide est refuse : l'authentification est cassee")
        self.assertIn("root", corps)


class HealthResteAccessibleTests(_ServeurLocalMixin, unittest.TestCase):
    """`/api/health` sert a l'ecran de connexion lui-meme : il doit rester
    joignable sans jeton, sinon plus personne ne peut se connecter."""

    _prefixe = "cinesort_auth_health_"

    def test_health_sans_jeton_repond_200(self) -> None:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        code = resp.status
        corps = json.loads(resp.read() or b"{}")
        conn.close()

        self.assertEqual(code, 200, "le retrait du bypass a coupe /api/health : plus aucun login possible")
        self.assertTrue(corps.get("ok"))


class LEnvironnementEstRENDUTests(unittest.TestCase):
    """Garde de la garde : le harnais ci-dessus ne doit rien laisser derriere lui.

    CE TEST EXISTE PARCE QUE LE DEFAUT S'EST PRODUIT. La premiere version posait
    `LOCALAPPDATA` sans jamais le restaurer, et 52 tests `[chromium]` sont tombes
    en `ERROR at setup` dans la batterie complete — pour un fichier qui passait
    parfaitement seul.

    On execute donc le cycle complet du mixin sur une classe jetable et on
    compare l'environnement AVANT et APRES.
    """

    def test_le_cycle_du_harnais_restaure_LOCALAPPDATA(self) -> None:
        class _Jetable(_ServeurLocalMixin):
            _prefixe = "cinesort_auth_garde_"

        avant = dict(os.environ)
        # `try/finally` : si `setUpClass` leve a mi-parcours, ce test ne doit pas
        # laisser l'environnement pollue pour ses voisins — le defaut qu'il garde
        # serait alors provoque PAR lui.
        try:
            _Jetable.setUpClass()
            pendant = os.environ.get("LOCALAPPDATA")
        finally:
            _Jetable.tearDownClass()
        apres = dict(os.environ)

        self.assertEqual(pendant, _Jetable._tmp, "le harnais n'a pas isole l'etat")
        self.assertEqual(
            apres.get("LOCALAPPDATA"),
            avant.get("LOCALAPPDATA"),
            "LOCALAPPDATA n'est pas restaure : Playwright ne trouvera plus son navigateur",
        )
        self.assertEqual(
            apres.get("CINESORT_DISABLE_LOCAL_AUTH"),
            avant.get("CINESORT_DISABLE_LOCAL_AUTH"),
            "le kill-switch n'est pas restaure : les tests voisins mesureraient un autre chemin",
        )

    def test_aucune_variable_n_est_AJOUTEE_ni_retiree(self) -> None:
        """Contre-epreuve large : le mixin ne doit toucher que ce qu'il annonce."""

        class _Jetable(_ServeurLocalMixin):
            _prefixe = "cinesort_auth_garde2_"

        avant = set(os.environ)
        try:
            _Jetable.setUpClass()
        finally:
            _Jetable.tearDownClass()

        self.assertEqual(set(os.environ), avant, "le harnais a ajoute ou retire une variable d'environnement")


if __name__ == "__main__":
    unittest.main()
