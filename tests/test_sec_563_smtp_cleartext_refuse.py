"""Issue #563 (CWE-319) — le mot de passe SMTP ne part jamais en clair.

Defaut d'origine : `send_email_report` ouvrait une session SMTP en clair des
que `port != 465 and use_tls == False`, puis appelait `smtp.login(user, password)`
dessus. Le toggle "STARTTLS" etant expose dans Parametres > Email, decocher une
case suffisait a envoyer le mot de passe en clair sur le reseau, sans le moindre
avertissement.

Ces tests ne se contentent pas de lire le retour booleen : ils font tourner un
VRAI serveur SMTP en clair sur 127.0.0.1 et regardent ce qui arrive REELLEMENT
sur la socket. L'assertion qui compte est "le serveur n'a jamais recu de commande
AUTH" — c'est-a-dire "le secret n'est pas parti", pas "la fonction a renvoye
False".

Deux gardes sont posees et testees separement :
  - garde 1 (configuration) : refus AVANT d'ouvrir la moindre socket ;
  - garde 2 (transport)     : refus si la socket etablie n'est pas chiffree,
                              meme quand la configuration pretend le contraire.
"""

from __future__ import annotations

import smtplib
import socket
import socketserver
import ssl
import threading
import unittest
from typing import Any, Dict, List
from unittest import mock

from cinesort.app import email_report
from tests._helpers import find_free_port as _find_free_port

# ---------------------------------------------------------------------------
# Serveur SMTP en clair, reel, sur 127.0.0.1
# ---------------------------------------------------------------------------


class _SmtpRecorder(socketserver.StreamRequestHandler):
    """Parle assez d'ESMTP pour que le vrai smtplib deroule une session complete."""

    def handle(self) -> None:  # pragma: no cover - execute dans un thread
        # Un client qui coupe brutalement (test du predicat sur socket nue) est
        # un cas NORMAL ici : on sort proprement au lieu de laisser socketserver
        # imprimer une trace qui polluerait la sortie de la suite.
        try:
            self._converse()
        except OSError:
            return

    def _converse(self) -> None:
        srv: Any = self.server
        srv.note_connection()
        self.wfile.write(b"220 127.0.0.1 ESMTP test-recorder\r\n")
        in_data = False
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if in_data:
                if line == ".":
                    in_data = False
                    self.wfile.write(b"250 2.0.0 Ok: queued\r\n")
                else:
                    srv.note_body(line)
                continue
            srv.note_command(line)
            verb = line.split(" ", 1)[0].upper()
            if verb == "EHLO":
                caps = ["250-127.0.0.1", "250-SIZE 33554432"]
                if srv.advertise_starttls:
                    caps.append("250-STARTTLS")
                caps.append("250-AUTH PLAIN LOGIN")
                caps.append("250 HELP")
                self.wfile.write(("\r\n".join(caps) + "\r\n").encode("ascii"))
            elif verb == "HELO":
                self.wfile.write(b"250 127.0.0.1\r\n")
            elif verb == "AUTH":
                self.wfile.write(b"235 2.7.0 Authentication successful\r\n")
            elif verb == "MAIL":
                self.wfile.write(b"250 2.1.0 Ok\r\n")
            elif verb == "RCPT":
                self.wfile.write(b"250 2.1.5 Ok\r\n")
            elif verb == "DATA":
                in_data = True
                self.wfile.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
            elif verb in ("RSET", "NOOP"):
                self.wfile.write(b"250 2.0.0 Ok\r\n")
            elif verb == "QUIT":
                self.wfile.write(b"221 2.0.0 Bye\r\n")
                return
            else:
                self.wfile.write(b"502 5.5.2 Command not implemented\r\n")


class _PlainSmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, *, advertise_starttls: bool = False) -> None:
        super().__init__(("127.0.0.1", port), _SmtpRecorder)
        self.advertise_starttls = advertise_starttls
        self._lock = threading.Lock()
        self.connections = 0
        self.commands: List[str] = []
        self.body_lines: List[str] = []

    def note_connection(self) -> None:
        with self._lock:
            self.connections += 1

    def note_command(self, line: str) -> None:
        with self._lock:
            self.commands.append(line)

    def note_body(self, line: str) -> None:
        with self._lock:
            self.body_lines.append(line)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "connections": self.connections,
                "commands": list(self.commands),
                "body": list(self.body_lines),
            }


class _SmtpServerCase(unittest.TestCase):
    """Base : demarre un serveur SMTP en clair reel, par test."""

    advertise_starttls = False
    password = "S3cret-Du-Compte-Mail"
    user = "thomas@example.com"

    def setUp(self) -> None:
        self.port = _find_free_port()
        self.server = _PlainSmtpServer(self.port, advertise_starttls=self.advertise_starttls)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _settings(self, **overrides: Any) -> Dict[str, Any]:
        base = {
            "email_smtp_host": "127.0.0.1",
            "email_smtp_port": self.port,
            "email_smtp_user": self.user,
            "email_smtp_password": self.password,
            "email_smtp_tls": False,
            "email_to": "dest@example.com",
            "email_smtp_timeout_s": 5,
        }
        base.update(overrides)
        return base

    def _send(self, **overrides: Any) -> bool:
        return email_report.send_email_report(
            self._settings(**overrides),
            "post_scan",
            {"run_id": "test", "data": {"rows": 1}},
        )

    def assert_no_secret_on_the_wire(self, snap: Dict[str, Any]) -> None:
        auth = [c for c in snap["commands"] if c.upper().startswith("AUTH")]
        self.assertEqual(auth, [], f"une commande AUTH a atteint le serveur en clair : {auth!r}")
        wire = "\n".join(snap["commands"] + snap["body"])
        self.assertNotIn(self.password, wire, "le mot de passe apparait en clair sur la socket")


# ---------------------------------------------------------------------------
# GARDE 1 — refus sur la configuration, avant toute connexion
# ---------------------------------------------------------------------------


class Garde1ConfigurationTests(_SmtpServerCase):
    def test_identifiants_sans_chiffrement_refuses_avant_connexion(self) -> None:
        """ROUGE sans le correctif : le serveur recevait AUTH avec le mot de passe."""
        sent = self._send(email_smtp_tls=False)
        snap = self.server.snapshot()

        self.assertFalse(sent, "un envoi refuse ne doit jamais retourner True")
        self.assert_no_secret_on_the_wire(snap)
        self.assertEqual(
            snap["connections"],
            0,
            "le refus doit intervenir AVANT d'ouvrir la socket : rien ne doit atteindre le serveur",
        )

    def test_sans_identifiants_lenvoi_en_clair_reste_possible(self) -> None:
        """Non-regression : c'est le SECRET qu'on protege, pas le rapport.

        Un relais sans authentification continue de fonctionner en clair. Si ce
        test rougit, le correctif est devenu trop large et casse un usage
        legitime.
        """
        sent = self._send(email_smtp_user="", email_smtp_password="", email_smtp_tls=False)
        snap = self.server.snapshot()

        self.assertTrue(sent, "un relais local sans identifiants doit continuer a fonctionner")
        self.assertEqual(snap["connections"], 1)
        verbs = [c.split(" ", 1)[0].upper() for c in snap["commands"]]
        self.assertIn("MAIL", verbs, f"le message doit avoir ete remis ; commandes = {snap['commands']!r}")
        self.assertIn("DATA", verbs)

    def test_mot_de_passe_sans_utilisateur_ne_declenche_pas_le_refus(self) -> None:
        """`smtp.login` n'est appele que si user ET password sont renseignes.

        La garde calque exactement cette condition : un mot de passe orphelin
        (sans utilisateur) ne transmet aucun secret, donc ne doit rien bloquer.
        """
        sent = self._send(email_smtp_user="", email_smtp_password="orphelin", email_smtp_tls=False)
        snap = self.server.snapshot()

        self.assertTrue(sent, "aucun AUTH n'aurait lieu : rien a proteger, rien a refuser")
        self.assert_no_secret_on_the_wire(snap)

    def test_starttls_demande_echoue_ferme_si_le_serveur_ne_loffre_pas(self) -> None:
        """Ce que fait STARTTLS ici, verifie sur un vrai serveur.

        Demander STARTTLS ne peut PAS retomber silencieusement en clair :
        `smtplib.SMTP.starttls()` leve SMTPNotSupportedError quand le serveur
        n'annonce pas la capacite. Le seul trou etait donc bien "ne pas demander
        STARTTLS du tout", ce que couvre la garde 1.
        """
        sent = self._send(email_smtp_tls=True)
        snap = self.server.snapshot()

        self.assertFalse(sent)
        self.assertEqual(snap["connections"], 1, "la garde 1 laisse passer : la connexion a bien eu lieu")
        self.assert_no_secret_on_the_wire(snap)


# ---------------------------------------------------------------------------
# Le message de refus doit nommer une sortie qui MARCHE
# ---------------------------------------------------------------------------


class MessageDeRefusTests(_SmtpServerCase):
    """Un refus qui ne dit pas quoi faire est une impasse, pas un garde-fou.

    Le serveur de ces tests est exactement le relais que le refus casse : il
    annonce `AUTH` mais **pas** `STARTTLS` (`advertise_starttls = False`), et
    rien n'ecoute en TLS implicite. Les deux sorties historiquement annoncees y
    echouent toutes les deux — c'est mesure ici sur la vraie socket, pas
    suppose. La seule qui aboutit est de retirer les identifiants, puisque
    c'est leur presence qui declenche le refus (garde 1). Le message doit donc
    la nommer.
    """

    advertise_starttls = False

    def test_le_message_nomme_les_trois_sorties(self) -> None:
        """ROUGE avant correctif : le message ne proposait que STARTTLS et 465.

        On n'assert pas la phrase entiere (elle doit pouvoir etre reformulee)
        mais les trois issues actionnables et les libelles exacts du formulaire
        Parametres > Notifications > Rapports email (SMTP).
        """
        msg = email_report.CLEARTEXT_REFUSAL_MESSAGE

        self.assertIn("STARTTLS", msg)
        self.assertIn("465", msg)
        self.assertIn("Utilisateur", msg, "le libelle exact du champ doit figurer dans le message")
        self.assertIn("Mot de passe", msg, "le libelle exact du champ doit figurer dans le message")
        self.assertIn(
            "videz",
            msg.lower(),
            "la seule sortie qui marche pour un relais AUTH-sans-TLS doit etre dite, pas sous-entendue",
        )
        self.assertIn("n'a pas ete transmis", msg, "l'utilisateur doit savoir que le secret est reste chez lui")

    def test_sortie_1_activer_starttls_echoue_sur_ce_relais(self) -> None:
        """`smtplib` leve SMTPNotSupportedError : le serveur n'annonce pas la capacite."""
        sent = self._send(email_smtp_tls=True)
        snap = self.server.snapshot()

        self.assertFalse(sent, "la premiere sortie annoncee ne peut pas aboutir sur ce relais")
        self.assertEqual(snap["connections"], 1)
        self.assert_no_secret_on_the_wire(snap)

    def test_sortie_2_passer_en_465_echoue_sur_ce_relais(self) -> None:
        """Basculer en TLS implicite ne marche que si le relais parle TLS.

        On redirige le port du TLS implicite vers le relais en clair du test :
        `send_email_report` prend alors la branche `SMTP_SSL`, et le handshake
        se casse sur la banniere `220 ...` lue comme un enregistrement TLS.
        Aucun mock du code teste : c'est un vrai `ssl` sur une vraie socket.
        """
        with mock.patch.object(email_report, "SMTP_IMPLICIT_TLS_PORT", self.port):
            sent = self._send(email_smtp_tls=False)
        snap = self.server.snapshot()

        self.assertFalse(sent, "la deuxieme sortie annoncee ne peut pas aboutir sur ce relais")
        self.assert_no_secret_on_the_wire(snap)

    def test_sortie_3_vider_les_identifiants_debloque_reellement_lenvoi(self) -> None:
        """La sortie que le message ajoute doit etre appliquee LITTERALEMENT et marcher.

        Meme relais, meme session de test : d'abord le refus, puis la consigne
        du message (« videz les champs Utilisateur et Mot de passe »), et le
        rapport part.
        """
        refuse = self._send(email_smtp_tls=False)
        self.assertFalse(refuse)
        self.assertEqual(self.server.snapshot()["connections"], 0, "la garde 1 doit refuser avant d'ouvrir la socket")

        sent = self._send(email_smtp_user="", email_smtp_password="", email_smtp_tls=False)
        snap = self.server.snapshot()

        self.assertTrue(sent, "la sortie annoncee par le message doit reellement debloquer l'envoi")
        self.assertEqual(snap["connections"], 1)
        verbs = [c.split(" ", 1)[0].upper() for c in snap["commands"]]
        self.assertIn("DATA", verbs, f"le rapport doit avoir ete remis ; commandes = {snap['commands']!r}")
        self.assert_no_secret_on_the_wire(snap)


# ---------------------------------------------------------------------------
# GARDE 2 — refus sur le transport reellement negocie
# ---------------------------------------------------------------------------


class _DriftedSmtp(smtplib.SMTP):
    """Client SMTP dont `starttls()` ne chiffre pas — la derive a couvrir.

    Tout le reste est du vrai `smtplib` : connexion, EHLO, `sock`, `login`. Rien
    n'est simule cote garde : la socket est une vraie socket TCP en clair, et
    c'est bien le predicat de production qui l'inspecte.
    """

    def starttls(self, *_args: Any, **_kwargs: Any) -> tuple:
        return (220, b"2.0.0 Ready to start TLS")


class Garde2TransportTests(_SmtpServerCase):
    advertise_starttls = True

    def test_socket_en_clair_bloque_le_login_meme_si_la_config_dit_tls(self) -> None:
        """ROUGE si la garde 2 saute : `login` part sur une socket non chiffree.

        Scenario : la configuration est saine (`use_tls=True`), la garde 1
        laisse donc passer, mais le transport ne chiffre pas. Seule une garde
        qui constate la socket peut attraper ce cas.
        """
        with mock.patch("smtplib.SMTP", _DriftedSmtp):
            sent = self._send(email_smtp_tls=True)
        snap = self.server.snapshot()

        self.assertFalse(sent, "session non chiffree : l'envoi doit echouer, pas se degrader")
        self.assertEqual(snap["connections"], 1, "la garde 1 a laisse passer, la connexion doit exister")
        self.assert_no_secret_on_the_wire(snap)

    def test_predicat_socket_sur_une_vraie_socket_en_clair(self) -> None:
        conn = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        self.addCleanup(conn.close)
        holder = mock.Mock()
        holder.sock = conn
        self.assertFalse(email_report._socket_is_encrypted(holder))

    def test_predicat_socket_sur_une_vraie_ssl_socket(self) -> None:
        """Controle positif : sans lui, un predicat qui renvoie toujours False
        passerait le test precedent sans rien prouver."""
        ctx = ssl.create_default_context()
        # TLS 1.2 minimum : CodeQL (py/insecure-protocol) signale a juste titre
        # qu'un contexte par defaut laisse la porte ouverte a TLSv1/1.1 selon la
        # politique OpenSSL locale. On ne handshake pas ici, mais un test de
        # securite n'a aucune raison de montrer le mauvais exemple.
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        raw = socket.socket()
        self.addCleanup(raw.close)
        wrapped = ctx.wrap_socket(raw, do_handshake_on_connect=False, server_hostname="example.invalid")
        self.addCleanup(wrapped.close)
        holder = mock.Mock()
        holder.sock = wrapped
        self.assertTrue(email_report._socket_is_encrypted(holder))

    def test_predicat_socket_sans_attribut(self) -> None:
        self.assertFalse(email_report._socket_is_encrypted(object()))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Predicat de configuration (pur)
# ---------------------------------------------------------------------------


class SessionWillBeEncryptedTests(unittest.TestCase):
    def test_port_465_est_chiffre_meme_toggle_off(self) -> None:
        """Le TLS implicite ne depend pas du toggle : `port == 465` -> SMTP_SSL."""
        self.assertTrue(email_report.smtp_session_will_be_encrypted(465, False))

    def test_587_avec_starttls(self) -> None:
        self.assertTrue(email_report.smtp_session_will_be_encrypted(587, True))

    def test_587_sans_starttls_est_en_clair(self) -> None:
        self.assertFalse(email_report.smtp_session_will_be_encrypted(587, False))

    def test_25_sans_starttls_est_en_clair(self) -> None:
        self.assertFalse(email_report.smtp_session_will_be_encrypted(25, False))

    def test_port_illisible_nest_pas_repute_chiffre(self) -> None:
        """Un port invalide ne doit pas ouvrir une porte : defaut restrictif."""
        self.assertFalse(email_report.smtp_session_will_be_encrypted("quatre-cent-soixante-cinq", False))
        self.assertFalse(email_report.smtp_session_will_be_encrypted(None, False))


class TestEmailButtonReportsTheReasonTests(unittest.TestCase):
    """Le bouton "Tester l'envoi" doit DIRE pourquoi il refuse.

    Sans cela l'utilisateur lit "Echec de l'envoi. Verifiez les parametres
    SMTP." et n'a aucun moyen de deviner que c'est le toggle STARTTLS. Le refus
    de securite reste dans `send_email_report` (il doit tenir quel que soit
    l'appelant) ; ce chemin ne fait que remonter le motif.
    """

    def _api_with(self, **settings: Any):
        import cinesort.ui.api.cinesort_api as api_mod

        api = api_mod.CineSortApi()
        base = {
            "email_smtp_host": "smtp.example.com",
            "email_to": "dest@example.com",
            "email_smtp_user": "thomas@example.com",
            "email_smtp_password": "S3cret",
            "email_smtp_port": 587,
            "email_smtp_tls": False,
        }
        base.update(settings)
        return api, mock.patch.object(api_mod.CineSortApi, "_internal_settings", return_value=base)

    def test_motif_explicite_et_aucun_envoi_tente(self) -> None:
        import cinesort.ui.api.cinesort_api as api_mod

        api, patcher = self._api_with()
        with patcher, mock.patch.object(api_mod._email_report_mod, "send_email_report") as envoi:
            result = api.integrations.test_email_report()

        self.assertFalse(result["ok"])
        self.assertIn("STARTTLS", result["message"])
        self.assertIn("465", result["message"])
        # La sortie qui marche pour un relais AUTH-sans-TLS doit atteindre
        # l'ECRAN, pas seulement le commentaire du code : c'est ici que
        # l'utilisateur lit le motif.
        self.assertIn("videz", result["message"].lower())
        self.assertIn("Mot de passe", result["message"])
        envoi.assert_not_called()

    def test_configuration_saine_declenche_bien_lenvoi(self) -> None:
        """Controle positif : le pre-vol ne doit pas bloquer un envoi legitime."""
        import cinesort.ui.api.cinesort_api as api_mod

        api, patcher = self._api_with(email_smtp_tls=True)
        with patcher, mock.patch.object(api_mod._email_report_mod, "send_email_report", return_value=True) as envoi:
            result = api.integrations.test_email_report()

        self.assertTrue(result["ok"])
        envoi.assert_called_once()


if __name__ == "__main__":
    unittest.main()
