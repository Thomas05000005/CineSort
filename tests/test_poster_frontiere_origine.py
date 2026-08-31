"""La route jaquettes distinguait les appelants par le SITE, pas par l'ORIGINE.

`_poster_trusted_caller` acceptait `Sec-Fetch-Site: same-site` comme fiable. Or
le « site » au sens Fetch Metadata est le domaine enregistrable : **le port n'en
fait pas partie**. Sur `127.0.0.1`, tout autre service web local est donc
`same-site`.

MESURE DU 2026-08-28 (navigateur reel, deux serveurs locaux, ports 18801/18802) :
une image demandee a un AUTRE PORT de la meme machine porte
`Sec-Fetch-Site: same-site`, pas `cross-site`. Puis, contre CineSort en bac a
sable : une page servie sur 18801 obtenait la jaquette en cache de l'instance du
18742 (image chargee, 1x1) et un refus sur un id absent. Deux consequences :

  1. ORACLE. Les deux reponses se distinguent, donc une page tierce peut tester
     id par id ce que le cache contient — c'est-a-dire enumerer la bibliotheque.
  2. PRIVILEGE. `same-site` etant classe FIABLE, cette page obtenait aussi
     `force=1` (purge du cache) et le fetch TMDb, pas seulement la lecture.

POURQUOI PERSONNE NE L'AVAIT VU. `_poster_trusted_caller` et `Sec-Fetch-Site`
n'apparaissaient dans AUCUN fichier de `tests/`. Leur unique exercice etait
`docs/internal/r8/r8_f3_poster_trusted_diff.py`, un script de diagnostic que nul
workflow ne lance — et dont la table de cas couvre `same-origin` et
`cross-site`, **jamais `same-site`**. L'en-tete a quatre valeurs ; la preuve en
enumerait deux, les deux extremes.

LE REPLI PAR IP EST LA SECONDE MOITIE DU DEFAUT. Exiger `same-origin` ne suffit
pas : un navigateur `same-site` sur la boucle locale retomberait sur
`_client_ip() in _LOCAL_CLIENT_IPS` et redeviendrait fiable. Des lors qu'un
`Sec-Fetch-Site` est present, l'appelant EST un navigateur et se prononce
lui-meme ; l'IP ne doit plus rien rattraper. Le repli reste pour les clients
non-navigateurs (pywebview natif, curl local), qui n'envoient pas cet en-tete.
"""

from __future__ import annotations

import email.message
import unittest
from http.client import HTTPConnection

# Le harnais de serveur local vit deja dans ce module : il restaure LOCALAPPDATA
# en `finally`, lecon payee par 52 `ERROR at setup` de Playwright. Le reutiliser
# plutot que le redupliquer, c'est ne pas repayer cette lecon de travers.
from test_auth_loopback_sans_bypass import _ServeurLocalMixin

from cinesort.infra.rest_server import _CineSortHandler
from cinesort.infra.state import default_state_dir

# PNG 1x1 valide : un stub non decodable ferait echouer un `<img>` pour la
# mauvaise raison (piege rencontre pendant la mesure du 2026-08-28).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da6364f8cf000501010025a50d5c00"
    "00000049454e44ae426082"
)


def _handler(ip: str, entetes: dict) -> _CineSortHandler:
    """Fabrique un handler nu pour interroger ses predicats de confiance."""
    obj = _CineSortHandler.__new__(_CineSortHandler)
    obj.client_address = (ip, 50000)
    msg = email.message.Message()
    for cle, valeur in entetes.items():
        msg[cle] = valeur
    obj.headers = msg
    obj.cors_origin = ""
    return obj


class FrontiereDeConfianceDeLaRouteJaquettesTests(unittest.TestCase):
    """Les QUATRE valeurs de `Sec-Fetch-Site`, pas seulement les deux extremes."""

    def test_depuis_la_boucle_locale_seul_same_origin_est_fiable(self) -> None:
        # 127.0.0.1 est la position REELLE de l'attaquant : un autre service web
        # tournant sur la machine de l'utilisateur.
        attendu = {
            "same-origin": True,
            "same-site": False,
            "cross-site": False,
            "none": False,
        }
        for valeur, fiable in attendu.items():
            with self.subTest(sec_fetch_site=valeur):
                handler = _handler("127.0.0.1", {"Sec-Fetch-Site": valeur})
                self.assertEqual(
                    handler._poster_trusted_caller(),
                    fiable,
                    f"Sec-Fetch-Site: {valeur} depuis la boucle locale",
                )

    def test_un_client_non_navigateur_local_reste_fiable(self) -> None:
        """CONTRE-TEST : pywebview natif et curl local n'envoient pas l'en-tete.

        Vert avant comme apres le correctif : c'est le comportement a NE PAS
        casser. Sans lui, durcir la frontiere couperait le desktop lui-meme.
        """
        self.assertTrue(_handler("127.0.0.1", {})._poster_trusted_caller())

    def test_depuis_le_LAN_la_meme_regle_s_applique(self) -> None:
        attendu = {"same-origin": True, "same-site": False, "cross-site": False}
        for valeur, fiable in attendu.items():
            with self.subTest(sec_fetch_site=valeur):
                handler = _handler("192.168.1.50", {"Sec-Fetch-Site": valeur})
                self.assertEqual(handler._poster_trusted_caller(), fiable, f"LAN, {valeur}")

    def test_un_client_non_navigateur_distant_reste_non_fiable(self) -> None:
        """CONTRE-TEST : curl depuis le LAN ne doit pas bruler le quota TMDb."""
        self.assertFalse(_handler("192.168.1.50", {})._poster_trusted_caller())


class LOracleDEnumerationEstFermeTests(_ServeurLocalMixin, unittest.TestCase):
    """Bout en bout, sur un VRAI serveur : la reponse ne doit pas trahir le cache."""

    _prefixe = "cinesort_poster_frontiere_"

    def _planter_une_jaquette(self, tmdb_id: int, taille: str = "w500") -> None:
        dossier = default_state_dir() / "cache" / "posters" / taille
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"{tmdb_id}.png").write_bytes(_PNG_1x1)

    def _get(self, tmdb_id: int, entetes: dict) -> int:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", f"/api/poster?id={tmdb_id}&size=w500", headers=entetes)
        reponse = conn.getresponse()
        code = reponse.status
        # Lire le corps AVANT de fermer : sans cela le serveur journalise un
        # `ConnectionAbortedError [WinError 10053]` par requete. Ce n'est pas un
        # echec, mais une sortie bruyante est la facon dont les vrais echecs se
        # perdent - cf. les `ERROR at setup` invisibles dans un grep FAILED.
        reponse.read()
        conn.close()
        return code

    def test_un_navigateur_same_site_ne_distingue_pas_cache_et_absence(self) -> None:
        """LE defaut : 200 sur un id en cache, 404 sur un id absent, sans jeton.

        Un seul bit suffit a un attaquant : il n'a pas besoin de l'image, juste
        de savoir si elle existe.
        """
        self._planter_une_jaquette(4242)
        entetes = {"Sec-Fetch-Site": "same-site", "Sec-Fetch-Dest": "image"}
        en_cache = self._get(4242, entetes)
        absent = self._get(4243, entetes)
        self.assertEqual(
            en_cache,
            absent,
            f"la reponse trahit le cache : en cache={en_cache}, absent={absent}",
        )

    def test_un_navigateur_same_origin_obtient_toujours_sa_jaquette(self) -> None:
        """CONTRE-TEST : le dashboard, lui, doit continuer a afficher ses images.

        C'est le seul consommateur legitime : il est servi par CE serveur, donc
        `same-origin`. Si ce test rougit, le correctif a casse le produit.
        """
        self._planter_une_jaquette(4244)
        code = self._get(4244, {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Dest": "image"})
        self.assertEqual(code, 200, f"le dashboard n'obtient plus ses jaquettes (status={code})")

    def test_un_client_non_navigateur_local_obtient_toujours_sa_jaquette(self) -> None:
        """CONTRE-TEST : aucun en-tete Sec-Fetch — pywebview natif, curl local."""
        self._planter_une_jaquette(4245)
        code = self._get(4245, {})
        self.assertEqual(code, 200, f"le client natif n'obtient plus ses jaquettes (status={code})")


if __name__ == "__main__":
    unittest.main()
