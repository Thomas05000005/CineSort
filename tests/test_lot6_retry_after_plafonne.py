"""LOT 6 (E) — un `Retry-After` long est dormi EN ENTIER, trois fois de suite.

`make_session_with_retry` pose `respect_retry_after_header=True` sur la `Retry`
partagee par TOUS les clients (TMDb, OMDb, Jellyfin, Radarr, Ollama, proxy de
jaquettes). Le constat de depart parlait d'une absence totale de plafond : ce
n'est pas exact, urllib3 en a un — `retry_after_max`, dont le defaut vaut
21600 s. Six heures PAR SOMMEIL, et jusqu'a `max_attempts` sommeils par appel.

Mesure faite avant correctif, contre un vrai serveur en boucle locale qui
repond `503` + `Retry-After: 3600`, avec `time.sleep` instrumente :

    sommeils demandes : [3600, 3600, 3600]   -> 3 heures dans un seul
                                                `session.get()`

Rien dans le produit ne peut absorber ca : le thread du handler REST, ou le
thread d'enrichissement de l'UI, y reste bloque, sans annulation possible et
sans que le timeout par requete n'ait la moindre prise (il borne une lecture de
socket, pas le sommeil entre deux tentatives).

Le correctif plafonne `retry_after_max`. La politesse est conservee pour toute
valeur realiste — TMDb et consorts repondent des `Retry-After` de l'ordre de la
seconde — et le pire cas redevient borne.
"""

from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List
from unittest import mock

import urllib3.util.retry as _retry_urllib3

from cinesort.infra import _http_utils
from cinesort.infra._http_utils import make_session_with_retry

#: Une heure : valeur qu'un serveur sature (ou usurpe) peut annoncer sans etre
#: malveillant. Elle doit etre RAMENEE au plafond, pas dormie.
RETRY_AFTER_ANNONCE = 3600

#: Plafond attendu, ecrit en dur ICI pour que le test echoue sur le
#: COMPORTEMENT et non sur un `ImportError` a la collecte.
PLAFOND_ATTENDU_S = 30


class _ServeurQuiDemandeUneHeure(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — signature imposee par BaseHTTPRequestHandler
        self.send_response(503)
        self.send_header("Retry-After", str(RETRY_AFTER_ANNONCE))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


class RetryAfterEstPlafonneTests(unittest.TestCase):
    def test_le_plafond_configure_borne_reellement_le_sommeil(self) -> None:
        """Mesure de bout en bout : socket reelle, `time.sleep` instrumente."""
        serveur = ThreadingHTTPServer(("127.0.0.1", 0), _ServeurQuiDemandeUneHeure)
        port = serveur.server_address[1]
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        sommeils: List[float] = []
        try:
            session = make_session_with_retry(max_attempts=3, backoff_base=0.5)
            with mock.patch.object(_retry_urllib3.time, "sleep", side_effect=sommeils.append):
                reponse = session.get(f"http://127.0.0.1:{port}/x", timeout=5)
        finally:
            serveur.shutdown()
            serveur.server_close()
            fil.join(timeout=5)

        self.assertEqual(reponse.status_code, 503)
        self.assertTrue(sommeils, "aucune retentative : le harnais ne mesure rien")
        self.assertLessEqual(
            max(sommeils),
            PLAFOND_ATTENDU_S,
            f"un sommeil de {max(sommeils):.0f} s a ete demande dans un seul session.get()",
        )
        self.assertLessEqual(
            sum(sommeils),
            PLAFOND_ATTENDU_S * 3,
            f"appel bloque {sum(sommeils):.0f} s au total",
        )

    def test_le_plafond_survit_aux_retentatives_successives(self) -> None:
        """urllib3 recree une `Retry` a chaque tentative (`Retry.new`).

        Un plafond qui ne serait pas recopie disparaitrait des la 2e tentative
        et le premier test, qui ne regarde que le maximum, resterait vert.
        """
        session = make_session_with_retry()
        retry = session.get_adapter("https://api.themoviedb.org/").max_retries
        for _ in range(3):
            retry = retry.new()
            self.assertEqual(retry.parse_retry_after(str(RETRY_AFTER_ANNONCE)), PLAFOND_ATTENDU_S)

    def test_le_plafond_est_une_constante_nommee_du_module(self) -> None:
        """Une valeur en dur dans `Retry(...)` serait invisible aux appelants."""
        self.assertEqual(getattr(_http_utils, "DEFAULT_RETRY_AFTER_MAX_S", None), PLAFOND_ATTENDU_S)

    def test_temoin_une_valeur_raisonnable_est_toujours_respectee(self) -> None:
        """Contre-test : plafonner n'est pas ignorer le header.

        Sans lui, `respect_retry_after_header=False` passerait aussi — et on
        retenterait immediatement un serveur qui demande une pause.
        """
        retry = make_session_with_retry().get_adapter("https://api.themoviedb.org/").max_retries
        self.assertTrue(retry.respect_retry_after_header)
        self.assertEqual(retry.parse_retry_after("2"), 2)


if __name__ == "__main__":
    unittest.main()
