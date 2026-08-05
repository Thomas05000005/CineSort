"""Construire un client ne doit JAMAIS resoudre le DNS.

Ces constructeurs sont appeles quand l'utilisateur enregistre ses parametres.
`socket.getaddrinfo` ne respecte PAS `socket.setdefaulttimeout` et peut tenir des
dizaines de secondes sur un hote injoignable — precisement le cas ou l'on
configure une URL pour la premiere fois, ou apres avoir eteint son serveur.

La protection contre le DNS rebinding n'est pas perdue pour autant : elle est
portee par `SsrfGuardHTTPAdapter`, qui verifie l'IP au moment de la CONNEXION.
C'est d'ailleurs le seul instant ou la verification ne peut pas etre contournee
par un changement de DNS entre la validation et la connexion (TOCTOU) — donc
resoudre dans le constructeur coutait cher SANS rien garantir de plus.

Releve par CodeRabbit sur la PR#898.
"""

from __future__ import annotations

import unittest
from unittest import mock

from cinesort.infra.jellyfin_client import JellyfinClient, JellyfinError
from cinesort.infra.plex_client import PlexClient, PlexError
from cinesort.infra.radarr_client import RadarrClient, RadarrError


class ConstructorsDoNotResolveDnsTests(unittest.TestCase):
    """Aucun appel a `socket.getaddrinfo` pendant la construction."""

    URL = "https://jellyfin.exemple.invalid:8096"

    def _compter_resolutions(self, construire) -> int:
        """Construit le client en comptant les appels a getaddrinfo.

        On patche dans le module `network_utils`, la ou l'appel est fait — pas
        `socket.getaddrinfo` globalement, qui serait aussi utilise par d'autres
        couches et rendrait le compte faux.
        """
        with mock.patch("cinesort.infra.network_utils.socket.getaddrinfo") as faux:
            faux.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            construire()
            return faux.call_count

    def test_jellyfin_ne_resout_pas(self) -> None:
        n = self._compter_resolutions(lambda: JellyfinClient(self.URL, "jeton"))
        self.assertEqual(n, 0, f"{n} resolution(s) DNS pendant la construction")

    def test_plex_ne_resout_pas(self) -> None:
        n = self._compter_resolutions(lambda: PlexClient(self.URL, "jeton"))
        self.assertEqual(n, 0, f"{n} resolution(s) DNS pendant la construction")

    def test_radarr_ne_resout_pas(self) -> None:
        n = self._compter_resolutions(lambda: RadarrClient(self.URL, "cle"))
        self.assertEqual(n, 0, f"{n} resolution(s) DNS pendant la construction")

    def test_la_validation_d_url_reste_active(self) -> None:
        """Non-regression : ne pas resoudre le DNS ne doit pas desarmer la garde.

        Une IP litterale de metadonnees cloud doit toujours etre refusee a la
        construction — cette verification-la ne demande aucune resolution.

        NB : chaque client leve SON type d'erreur (`JellyfinError`, `PlexError`,
        `RadarrError`), pas un `ValueError` commun. On verifie donc le refus et
        son MOTIF, ce qui prouve en plus que c'est bien la garde d'URL qui a
        parle et non une panne quelconque du constructeur.
        """
        cas = (
            (JellyfinClient, JellyfinError, "jeton"),
            (PlexClient, PlexError, "jeton"),
            (RadarrClient, RadarrError, "cle"),
        )
        for classe, erreur, secret in cas:
            with self.subTest(client=classe.__name__):
                with self.assertRaises(erreur) as ctx:
                    classe("http://169.254.169.254/latest/meta-data/", secret)
                self.assertIn("169.254.169.254", str(ctx.exception))
                self.assertIn("metadata", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
