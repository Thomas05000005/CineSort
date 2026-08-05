"""Issue #516 — la reponse de l'API GitHub est lue avec une borne.

Defaut d'origine : `_fetch_latest_release` faisait `resp.read()` sans argument,
c'est-a-dire "lis jusqu'a EOF". Tout ce qui repond a la place de
`api.github.com` (portail captif, proxy, MITM) faisait donc allouer autant de
memoire qu'il envoyait d'octets, sans aucun plafond.

Le motif retenu est `resp.read(MAX + 1)` : la borne est portee PAR l'appel de
lecture. C'est ce qui le distingue du faux garde `if len(corps_entier) > N`,
ou le corps est deja integralement en memoire quand la comparaison s'evalue.
Les tests ci-dessous mesurent donc ce qui a ete REELLEMENT lu, pas seulement
la valeur de retour.

Un test tourne sans aucun mock : vrai serveur HTTP sur 127.0.0.1, vrai
`urlopen`, vrai `HTTPResponse`.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from cinesort.app import updater
from tests._helpers import find_free_port as _find_free_port
from tests.test_updater import _fake_payload, _FakeResponse

_MAX = updater.MAX_RELEASE_PAYLOAD_BYTES


def _payload_of_size(total: int) -> bytes:
    """JSON de release valide, rembourre pour peser EXACTEMENT `total` octets."""
    base = _fake_payload(body="")
    encoded = json.dumps(base).encode("utf-8")
    padding = total - len(encoded)
    if padding < 0:
        raise ValueError("taille demandee trop petite pour un payload valide")
    base["body"] = "x" * padding
    out = json.dumps(base).encode("utf-8")
    # Le rembourrage se fait a l'octet pres : "x" pese 1 octet en UTF-8 et en JSON.
    assert len(out) == total, (len(out), total)
    return out


class BoundedReadWithRealSocketTests(unittest.TestCase):
    """Zero mock : vrai serveur HTTP, vrai urlopen, vrai HTTPResponse."""

    def setUp(self) -> None:
        self.body = b""
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - signature imposee
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(outer.body)))
                self.end_headers()
                self.wfile.write(outer.body)

            def log_message(self, *_args: object) -> None:
                return

        self.port = _find_free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown)
        self._base = mock.patch.object(updater, "GITHUB_API_BASE", f"http://127.0.0.1:{self.port}")
        self._base.start()
        self.addCleanup(self._base.stop)

    def _shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_corps_au_dela_du_plafond_refuse(self) -> None:
        """ROUGE sans le correctif : le corps entier etait avale puis parse."""
        self.body = _payload_of_size(_MAX + 4096)
        result = updater._fetch_latest_release("foo/cinesort", 5)
        self.assertIsNone(result, "un corps hors plafond doit etre refuse, pas parse")

    def test_corps_normal_toujours_lu(self) -> None:
        """Controle positif : sans lui, un fetch casse rendrait le test precedent
        vert sans rien prouver."""
        self.body = _payload_of_size(4096)
        result = updater._fetch_latest_release("foo/cinesort", 5)
        self.assertIsNotNone(result)
        self.assertEqual(result["tag_name"], "7.7.0")  # type: ignore[index]

    def test_corps_exactement_au_plafond_accepte(self) -> None:
        """La borne est un plafond inclusif : MAX octets passent, MAX+1 non.

        Verrouille le sens de l'inegalite ; un `>=` a la place du `>` ferait
        rougir ce test.
        """
        self.body = _payload_of_size(_MAX)
        result = updater._fetch_latest_release("foo/cinesort", 5)
        self.assertIsNotNone(result, "un corps pile au plafond doit rester accepte")

    def test_corps_un_octet_au_dessus_du_plafond_refuse(self) -> None:
        self.body = _payload_of_size(_MAX + 1)
        self.assertIsNone(updater._fetch_latest_release("foo/cinesort", 5))


class AllocationIsBoundedTests(unittest.TestCase):
    """Mesure ce qui a ete REELLEMENT lu du flux, pas seulement le retour."""

    def test_lecture_ne_depasse_jamais_le_plafond(self) -> None:
        """ROUGE sans le correctif : `read()` sans borne aspirait les 8 Mio.

        C'est l'assertion qui distingue une vraie borne d'un test a posteriori
        sur un corps deja alloue.
        """
        enorme = b'{"tag_name": "9.9.9", "body": "' + b"x" * (8 * 1024 * 1024) + b'"}'
        resp = _FakeResponse(raw=enorme)
        with mock.patch.object(updater, "urlopen", return_value=resp):
            result = updater._fetch_latest_release("foo/cinesort", 5)

        self.assertIsNone(result)
        self.assertLessEqual(
            resp.total_bytes_yielded,
            _MAX + 1,
            f"{resp.total_bytes_yielded} octets ont ete lus alors que le plafond est {_MAX}",
        )
        self.assertIsNotNone(resp.max_amt_requested, "la lecture doit etre bornee, pas un read() nu")
        self.assertLessEqual(resp.max_amt_requested or 0, _MAX + 1)

    def test_reponse_non_utf8_ne_remonte_pas_dexception(self) -> None:
        """Meme scenario d'attaque : un serveur hostile renvoie des octets
        arbitraires. `UnicodeDecodeError` derive de ValueError et non de
        json.JSONDecodeError : elle traversait le `except`."""
        resp = _FakeResponse(raw=b"\xff\xfe\x00\x01 pas de l'utf-8")
        with mock.patch.object(updater, "urlopen", return_value=resp):
            self.assertIsNone(updater._fetch_latest_release("foo/cinesort", 5))

    def test_plafond_reste_genereux_pour_une_vraie_release(self) -> None:
        """Le plafond ne doit pas devenir une limite fonctionnelle.

        GitHub borne le corps d'une release a 125 000 caracteres ; on garde au
        moins un ordre de grandeur de marge au-dessus.
        """
        self.assertGreaterEqual(_MAX, 10 * 125_000)


if __name__ == "__main__":
    unittest.main()
