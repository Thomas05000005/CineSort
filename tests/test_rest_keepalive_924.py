"""Le serveur REST doit REUTILISER la connexion, pas en ouvrir une par requete.

Issue #924. `BaseHTTPRequestHandler` annonce HTTP/1.0 par defaut : la connexion
est fermee apres CHAQUE reponse. Une socket neuve par requete, et une entree de
plus en TIME_WAIT (4 min sur Windows).

Consequence mesuree en CI : Chromium finissait par rendre
`net::ERR_NO_BUFFER_SPACE` sur le chargement de `app.js`. Aucun JS n'etait donc
evalue et le shell restait cache — pendant que le serveur, lui, ACCEPTAIT
encore, ce qui a longtemps fait chercher au mauvais endroit.

Le tableau de bord est un client bavard : compteurs de la barre laterale toutes
les 30 s, notifications, badge de mise a jour. Chaque sondage brulait un port
ephemere.

MESURE, PAS CHRONOMETRE : on compte des CONNEXIONS ACCEPTEES. Un ratio de
durees sur un runner partage n'est pas une mesure, c'est un tirage — ce depot a
deja perdu des heures de CI sur un test de perf construit ainsi.
"""

from __future__ import annotations

import http.client
import threading
import time
import unittest

from cinesort.infra.rest_server import RestApiServer, _CineSortHandler
from cinesort.ui.api import cinesort_api as backend
from tests._helpers import find_free_port


class _CompteurDeConnexions:
    """Compte les acceptations en enveloppant la methode du serveur."""

    def __init__(self, serveur) -> None:
        self.n = 0
        self._lock = threading.Lock()
        self._vrai = serveur.get_request

        def _compte():
            with self._lock:
                self.n += 1
            return self._vrai()

        serveur.get_request = _compte


class RestKeepAliveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = backend.CineSortApi()
        self.port = find_free_port()
        self.srv = RestApiServer(self.api, port=self.port, token="t")
        self.srv.start()
        time.sleep(0.2)
        self.addCleanup(self.srv.stop)
        self.compteur = _CompteurDeConnexions(self.srv._server)

    def _n_requetes(self, n: int) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            for _ in range(n):
                conn.request("GET", "/api/health")
                conn.getresponse().read()
        finally:
            conn.close()

    def test_dix_requetes_tiennent_en_UNE_connexion(self) -> None:
        """Le coeur du correctif : 10 requetes, 1 socket."""
        self._n_requetes(10)
        self.assertEqual(
            self.compteur.n,
            1,
            f"{self.compteur.n} connexions pour 10 requetes — la connexion n'est pas reutilisee",
        )

    def test_le_serveur_annonce_HTTP_1_1(self) -> None:
        """HTTP/1.0 ne permet PAS le keep-alive : c'est la cause racine."""
        self.assertEqual(_CineSortHandler.protocol_version, "HTTP/1.1")

    def test_un_delai_d_inactivite_est_pose(self) -> None:
        """Corollaire OBLIGATOIRE du keep-alive.

        Sans lui (le defaut est `None`), une connexion persistante retient son
        thread INDEFINIMENT : on aurait deplace la fuite des sockets vers les
        threads, pas supprimee.
        """
        self.assertIsNotNone(
            _CineSortHandler.timeout,
            "keep-alive SANS delai d'inactivite : les threads s'accumulent a la place des sockets",
        )
        self.assertLessEqual(_CineSortHandler.timeout, 120)

    def test_la_reponse_porte_un_Content_Length(self) -> None:
        """HTTP/1.1 sans Content-Length exact fait ATTENDRE le client.

        C'est la condition qui rend le keep-alive sur : sans elle, le
        navigateur reste bloque a attendre un corps qui ne vient plus.
        """
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            corps = resp.read()
            self.assertIsNotNone(resp.getheader("Content-Length"), "reponse sans Content-Length")
            self.assertEqual(int(resp.getheader("Content-Length")), len(corps))
        finally:
            conn.close()

    def test_un_corps_REFUSE_ferme_la_connexion(self) -> None:
        """Le piege du keep-alive : ne jamais garder vivante une connexion
        dont on n'a pas consomme le corps.

        Le rejet 413 ne LIT pas le corps, et le drain refuse lui aussi au-dela
        de la borne (vider 17 Mo pour les jeter serait un amplificateur de
        DoS). En HTTP/1.1, ces octets seraient interpretes comme la requete
        SUIVANTE : la connexion se desynchronise et le client attend une
        reponse qui ne viendra jamais.

        Mesure : sans la fermeture explicite, activer le keep-alive faisait
        passer `test_08_max_body_size_17mo_rejet_propre` de « rejet propre » a
        TimeoutError.
        """
        from cinesort.infra import rest_server as rest_mod

        trop_gros = rest_mod._MAX_BODY_SIZE + 1024
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/run/get_status")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(trop_gros))
            conn.putheader("Authorization", "Bearer t")
            conn.endheaders()
            resp = conn.getresponse()  # doit repondre SANS attendre le corps
            resp.read()
            self.assertEqual(resp.status, 413)
            self.assertEqual(
                resp.getheader("Connection", "").lower(),
                "close",
                "corps non consomme et connexion gardee vivante : desynchronisation garantie",
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
