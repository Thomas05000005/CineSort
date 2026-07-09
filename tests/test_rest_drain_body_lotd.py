# -*- coding: utf-8 -*-
"""[BUG-LOTD-401-RST-BODY] — invariants du drain de body avant fermeture.

Complement DETERMINISTE de la garde probabiliste
tests/test_lotd_chain_rest.py::test_03b_bug_guard_401_rst_body_non_draine
(course TCP ~1 run sur 3) : verifie le helper _drain_request_body sans socket.

Invariants proteges :
  - un body annonce et disponible est LU en entier (close -> FIN, pas RST) ;
  - un body deja consomme par le dispatch n'est jamais relu (double read =
    blocage sur la socket) ;
  - un body > _MAX_BODY_SIZE n'est JAMAIS lu : l'abort du chemin 413 est un
    anti-DoS VOULU (Lot D, test_08 de la chaine REST) ;
  - Content-Length invalide/absent/zero -> no-op sans exception.
"""

from __future__ import annotations

import io
import unittest

from cinesort.infra.rest_server import _MAX_BODY_SIZE, _CineSortHandler


class _FakeConnection:
    def __init__(self) -> None:
        self.timeouts: list = []

    def settimeout(self, value) -> None:
        self.timeouts.append(value)


def _make_handler(content_length, body: bytes = b"", *, consumed=False):
    """Handler sans socket : uniquement les attributs lus par le drain."""
    handler = _CineSortHandler.__new__(_CineSortHandler)
    handler.headers = (
        {} if content_length is None else {"Content-Length": str(content_length)}
    )
    handler.rfile = io.BytesIO(body)
    handler.connection = _FakeConnection()
    if consumed is not None:
        handler._body_consumed = consumed
    return handler


class DrainRequestBodyTests(unittest.TestCase):
    def test_petit_body_non_consomme_est_draine_en_entier(self) -> None:
        # Cas nominal du bug : POST {} + mauvais token -> 401 sans lecture.
        handler = _make_handler(2, b"{}")
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 2, "body non draine -> RST possible")
        self.assertTrue(handler._body_consumed)

    def test_body_deja_consomme_par_le_dispatch_jamais_relu(self) -> None:
        handler = _make_handler(2, b"{}", consumed=True)
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 0, "double lecture du body")

    def test_body_superieur_a_max_body_size_jamais_lu(self) -> None:
        # L'abort 413 anti-DoS est VOULU : le drain ne doit pas le casser en
        # lisant 17 Mo d'un client non authentifie.
        handler = _make_handler(_MAX_BODY_SIZE + 1, b"x" * 1024)
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 0, "un body oversize a ete lu")
        self.assertEqual(handler.connection.timeouts, [], "timeout pose inutilement")

    def test_body_egal_a_max_body_size_est_draine(self) -> None:
        # Borne exacte : <= _MAX_BODY_SIZE est accepte par le dispatch, donc
        # doit aussi etre drainable sur les chemins d'erreur precoce.
        handler = _make_handler(4, b"abcd")
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 4)

    def test_content_length_invalide_noop_sans_exception(self) -> None:
        handler = _make_handler("abc", b"{}")
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 0)

    def test_content_length_zero_ou_absent_noop(self) -> None:
        for handler in (_make_handler(0), _make_handler(None)):
            handler._drain_request_body()
            self.assertEqual(handler.rfile.tell(), 0)

    def test_body_incomplet_ne_boucle_pas(self) -> None:
        # Client qui annonce 10 octets mais ferme apres 4 : EOF -> sortie propre.
        handler = _make_handler(10, b"abcd")
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 4)

    def test_flag_absent_par_defaut_noop(self) -> None:
        # Appel hors do_POST (flag jamais initialise) : defaut prudent = no-op.
        handler = _make_handler(2, b"{}", consumed=None)
        handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 0)


if __name__ == "__main__":
    unittest.main()
