"""L'instrument de #924 doit mesurer — et surtout ne jamais casser son rapport.

#924 : le shell du dashboard n'apparait parfois JAMAIS en CI (30 s de timeout,
donc « jamais » et non « lent »), et un `net::ERR_NO_BUFFER_SPACE` a deja ete
observe sur le meme workflow. La piste de l'epuisement de sockets est COHERENTE
avec trois faits et demontree par aucun : le nombre de sockets n'a jamais ete
mesure pendant un echec. L'issue le dit elle-meme — capturer l'etat reseau a
l'instant de l'echec donnerait le verdict en une seule occurrence, au lieu de
raisonner par elimination.

LE CONTRAT LE PLUS IMPORTANT EST « NE LEVE JAMAIS ». Un instrument qui plante
remplace l'echec qu'il documente par le sien. Ce n'est pas theorique : la
premiere version de `comptes_tcp` levait un `AttributeError` des son premier
appel reel, parce que `text=True` decodait la sortie de `netstat` en cp1252 et
que le thread de lecture de `subprocess` mourait sur l'octet 0x90 — laissant
`proc.stdout` a `None`. Le test le plus severe de ce fichier est donc celui qui
force la mesure a exploser.

MESURE DU JOUR (poste de developpement, hors CI) :

    connexions TCP locales : 147 (CLOSE_WAIT=4, ESTABLISHED=17,
                                  LISTENING=34, TIME_WAIT=92)

92 `TIME_WAIT` au repos : la grandeur existe, elle est lisible, et c'est
exactement celle que #924 reclame.
"""

from __future__ import annotations

import socket
import unittest

from tests import _diag_reseau
from tests._diag_reseau import comptes_tcp, etat_reseau, joignabilite


class LaJOIGNABILITEDitLaVeriteTests(unittest.TestCase):
    def test_un_port_qui_ECOUTE_est_dit_joignable(self) -> None:
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            code, phrase = joignabilite(port)

        self.assertEqual(code, 0)
        self.assertIn("joignable", phrase)
        self.assertIn(str(port), phrase, "la phrase ne nomme pas le port mesure")

    def test_un_port_FERME_est_dit_refuse(self) -> None:
        """C'est CE cas qui trancherait #924 : un port qui n'accepte plus
        expliquerait un shell qui n'apparait jamais, la ou « lent » ne
        l'expliquerait pas."""
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
        code, phrase = joignabilite(port)

        self.assertNotEqual(code, 0, "un port ferme est annonce joignable")
        self.assertIn("REFUSE", phrase)

    def test_un_port_ABSURDE_ne_leve_pas_et_le_DIT(self) -> None:
        code, phrase = joignabilite(999999)

        self.assertIsNone(code)
        self.assertIn("OverflowError", phrase, "l'exception n'est pas rapportee : la mesure se tait")

    def test_un_port_ILLISIBLE_ne_leve_pas_non_plus(self) -> None:
        code, phrase = joignabilite("pas-un-port")  # type: ignore[arg-type]

        self.assertIsNone(code)
        self.assertIn("illisible", phrase)


class LeCOMPTEDesSocketsEstLaGrandeurQueCherche924Tests(unittest.TestCase):
    def test_les_etats_TCP_sont_comptes_ou_l_absence_est_EXPLIQUEE(self) -> None:
        """Un `None` muet ne servirait a rien : si `netstat` manque, le rapport
        doit le dire, sinon on relirait « aucune connexion » comme un fait."""
        comptes, phrase = comptes_tcp()

        self.assertTrue(phrase.strip(), "la mesure n'a produit aucune phrase")
        if comptes is None:
            # UN SKIP NE DOIT PAS COUVRIR UNE REGRESSION. `netstat` ABSENT est
            # une raison legitime de sauter ; `netstat` present mais dont la
            # sortie n'est ni lue ni analysee en est une d'ECHOUER — c'est
            # exactement ce que produisait le decodage cp1252, et un skip
            # l'aurait rendu invisible.
            self.assertIn(
                "indisponible",
                phrase,
                f"netstat a repondu mais sa sortie n'a pas ete exploitee : {phrase}",
            )
            self.skipTest(f"netstat absent de ce poste : {phrase}")
        self.assertGreater(sum(comptes.values()), 0, "aucune connexion TCP : la mesure ne mesure rien")
        self.assertTrue(
            all(v > 0 for v in comptes.values()),
            "un etat est compte a zero : la categorie a ete inventee",
        )

    def test_l_etat_d_une_connexion_OUVERTE_est_visible(self) -> None:
        """Le compte doit bouger avec la realite, sinon il pourrait etre une
        constante et personne ne s'en apercevrait."""
        avant, _ = comptes_tcp()
        if avant is None:
            self.skipTest("netstat indisponible sur ce poste")
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            apres, _ = comptes_tcp()

        self.assertIsNotNone(apres)
        assert apres is not None  # pour l'analyse statique
        self.assertGreaterEqual(
            apres.get("LISTENING", 0),
            avant.get("LISTENING", 0) + 1,
            "ouvrir un port en ecoute n'a pas fait bouger le compte : la mesure est figee",
        )


class LInstrumentNeCASSEJamaisSonRapportTests(unittest.TestCase):
    """LE contrat qui compte. Un diagnostic qui plante efface l'echec qu'il
    documente — et cette version-ci l'a deja fait une fois."""

    def test_une_mesure_qui_EXPLOSE_devient_une_phrase(self) -> None:
        def boum() -> None:
            raise RuntimeError("le compteur a explose")

        original = _diag_reseau.comptes_tcp
        _diag_reseau.comptes_tcp = boum  # type: ignore[assignment]
        try:
            texte = etat_reseau(80)
        finally:
            _diag_reseau.comptes_tcp = original  # type: ignore[assignment]

        self.assertIn("le compteur a explose", texte, "l'echec de la mesure n'est pas rapporte")
        self.assertIn("RuntimeError", texte)
        self.assertIn("connect_ex", texte, "l'autre mesure a ete emportee par la premiere")

    def test_les_DEUX_mesures_peuvent_exploser_sans_lever(self) -> None:
        def boum() -> None:
            raise OSError("plus rien ne marche")

        originaux = (_diag_reseau.joignabilite, _diag_reseau.comptes_tcp)
        _diag_reseau.joignabilite = lambda _p: boum()  # type: ignore[assignment]
        _diag_reseau.comptes_tcp = boum  # type: ignore[assignment]
        try:
            texte = etat_reseau(80)
        finally:
            _diag_reseau.joignabilite, _diag_reseau.comptes_tcp = originaux  # type: ignore[assignment]

        self.assertEqual(texte.count("plus rien ne marche"), 2)

    def test_le_texte_assemble_porte_les_DEUX_mesures(self) -> None:
        texte = etat_reseau(80)

        self.assertIn("connect_ex", texte)
        self.assertIn("connexions TCP", texte)
        self.assertEqual(len(texte.splitlines()), 2, "le rapport n'a pas la forme attendue")


if __name__ == "__main__":
    unittest.main()
