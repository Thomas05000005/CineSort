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
import time
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

    def test_un_port_FERME_n_est_PAS_dit_joignable(self) -> None:
        """C'est CE cas qui trancherait #924. Deux issues sont legitimes selon la
        pile locale — un REFUS explicite, ou AUCUNE REPONSE (un pare-feu qui
        jette en silence) — et l'instrument doit dire LAQUELLE. Ce test n'en
        impose donc pas une : il exige que le port ne soit pas annonce joignable,
        et que la phrase nomme le mecanisme observe.

        Ce test a deja VERROUILLE une etiquette FAUSSE : il exigeait « REFUSE »
        sur un code 10035 (`WSAEWOULDBLOCK`), qui ne veut pas dire « refuse »
        mais « je ne sais pas encore ».
        """
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
        code, phrase = joignabilite(port)

        self.assertNotEqual(code, 0, "un port ferme est annonce joignable")
        self.assertNotIn("joignable", phrase)
        self.assertTrue(
            "REFUSE" in phrase or "AUCUNE REPONSE" in phrase,
            f"la phrase ne nomme pas le mecanisme observe : {phrase}",
        )

    def test_un_port_HORS_PLAGE_est_refuse_SANS_attendre(self) -> None:
        """MESURE : `create_connection(("127.0.0.1", 999999))` ne leve pas, elle
        EXPIRE. Sans borne explicite, l'instrument rapportait donc « aucune
        reponse » — une panne reseau — pour une erreur de programmation, apres
        avoir paye le delai complet."""
        debut = time.monotonic()
        code, phrase = joignabilite(999999)
        duree = time.monotonic() - debut

        self.assertIsNone(code)
        self.assertIn("hors plage", phrase)
        self.assertLess(duree, 0.5, f"la borne n'a pas court-circuite la sonde ({duree:.2f} s)")

    def test_un_port_INCONNU_donne_quand_meme_les_COMPTES(self) -> None:
        """MESURE SUR PYTEST (bac a sable dedie, deux fixtures) :

            serveur OK + fixture de page qui echoue -> funcargs CONTIENT e2e_server
                                                       et son port  (c'est le cas #924)
            fixture serveur qui echoue elle-meme    -> e2e_server ABSENT de funcargs

        Le second cas ne doit pas produire un silence : c'est justement quand le
        serveur ne demarre pas qu'on veut savoir si la machine a encore des
        sockets. Les comptes, eux, se mesurent sans port.
        """
        code, phrase = joignabilite(None)

        self.assertIsNone(code)
        self.assertIn("port inconnu", phrase)

        texte = etat_reseau(None)
        self.assertIn("port inconnu", texte)
        self.assertIn("connexions TCP", texte, "sans port, la mesure des sockets a ete perdue elle aussi")

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

    #: Sockets ouverts d'un coup, et marge toleree. Le compteur est celui de la
    #: MACHINE ENTIERE : exiger « +1 » exactement rendait le test dependant du
    #: bruit — n'importe quel autre processus fermant un port d'ecoute dans la
    #: fenetre de mesure le faisait rougir, et le runner de CI demarre justement
    #: des serveurs REST et des navigateurs Playwright. On en ouvre assez pour
    #: que le signal domine le bruit, et on tolere qu'il s'en ferme quelques-uns.
    _SOCKETS_TEMOINS = 25
    _MARGE_BRUIT = 5

    def test_le_compte_BOUGE_avec_la_realite(self) -> None:
        """Sans cela le compteur pourrait etre une constante, et personne ne
        s'en apercevrait."""
        avant, _ = comptes_tcp()
        if avant is None:
            self.skipTest("netstat indisponible sur ce poste")
        ouverts = []
        try:
            for _ in range(self._SOCKETS_TEMOINS):
                s = socket.socket()
                s.bind(("127.0.0.1", 0))
                s.listen(1)
                ouverts.append(s)
            apres, _ = comptes_tcp()
        finally:
            for s in ouverts:
                s.close()

        self.assertIsNotNone(apres)
        assert apres is not None  # pour l'analyse statique
        gagnes = apres.get("LISTENING", 0) - avant.get("LISTENING", 0)
        self.assertGreaterEqual(
            gagnes,
            self._SOCKETS_TEMOINS - self._MARGE_BRUIT,
            f"{self._SOCKETS_TEMOINS} ports d'ecoute ouverts, {gagnes} vu(s) : la mesure est figee",
        )


class LesETATSAvecUnCHIFFRESontComptesTests(unittest.TestCase):
    """`FIN_WAIT_1` ET `FIN_WAIT_2` PORTENT UN CHIFFRE.

    Le premier filtre (`etat.replace("_", "").isalpha()`) les rejetait en
    silence — eux et leurs variantes Linux `FIN_WAIT1`/`FIN_WAIT2`. Ils
    disparaissaient du detail ET du total, sans un mot. Or `FIN_WAIT_*` est une
    des familles qui s'accumulent quand une table de sockets deborde :
    l'instrument pouvait rendre un chiffre rassurant a l'instant precis ou il
    fallait s'alarmer.

    Mesure apres correction, sur ce poste : `FIN_WAIT_2=1` apparait.
    """

    def test_le_motif_d_etat_accepte_les_chiffres(self) -> None:
        from tests._diag_reseau import _ETAT_TCP

        for etat in ("FIN_WAIT_1", "FIN_WAIT_2", "FIN_WAIT1", "FIN_WAIT2", "TIME_WAIT", "SYN_RECV"):
            self.assertTrue(_ETAT_TCP.match(etat), f"{etat} serait silencieusement ecarte du total")

    def test_il_REJETTE_ce_qui_n_est_pas_un_etat(self) -> None:
        """Le filtre ne doit pas devenir permissif au point d'inventer des
        categories a partir d'adresses ou de ports tronques."""
        from tests._diag_reseau import _ETAT_TCP

        for pas_un_etat in ("0.0.0.0:135", "80", "*:*", "[::]:445", "_PRIVE"):
            self.assertFalse(_ETAT_TCP.match(pas_un_etat), f"{pas_un_etat} serait compte comme un etat")


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
        self.assertIn("127.0.0.1:80", texte, "l'autre mesure a ete emportee par la premiere")

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

        self.assertIn("127.0.0.1:80", texte)
        self.assertIn("connexions TCP", texte)
        self.assertEqual(len(texte.splitlines()), 2, "le rapport n'a pas la forme attendue")


if __name__ == "__main__":
    unittest.main()
