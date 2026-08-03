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
import socket
import threading
import time as _time
import unittest
from unittest import mock

import cinesort.infra.rest_server as rest_server
from cinesort.infra.rest_server import (
    _DRAIN_BODY_MAX_WALL_S,
    _MAX_BODY_SIZE,
    _CineSortHandler,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.timeouts: list = []

    def settimeout(self, value) -> None:
        self.timeouts.append(value)


def _make_handler(content_length, body: bytes = b"", *, consumed=False):
    """Handler sans socket : uniquement les attributs lus par le drain."""
    handler = _CineSortHandler.__new__(_CineSortHandler)
    handler.headers = {} if content_length is None else {"Content-Length": str(content_length)}
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


class _SlowDripFakeReader:
    """rfile d'un client 'slow drip' modelisant un BufferedReader.

    - read1(n) rend AU PLUS UN paquet (1 octet ici) : la boucle du drain reprend
      la main a chaque paquet et peut re-tester la deadline wall-clock.
    - read(n) est INTERDIT. Le vrai BufferedReader.read(n) BOUCLE des recv() pour
      accumuler n octets et ne rend jamais la main sous un client lent ; le drain
      DOIT donc utiliser read1(). Un appel a read() = regression SEC-1 -> on
      echoue immediatement (au lieu de hanger le test).
    """

    def __init__(self) -> None:
        self.reads = 0

    def read1(self, _n: int) -> bytes:
        self.reads += 1
        return b"x"

    def read(self, _n: int) -> bytes:  # pragma: no cover - doit ne jamais etre appele
        raise AssertionError(
            "drain a appele rfile.read() au lieu de read1() : regression SEC-1 "
            "(read() bloque en accumulant n octets -> deadline wall-clock inefficace)"
        )


class _FakeClock:
    """time.monotonic() deterministe : avance de `step` s a chaque appel."""

    def __init__(self, step: float) -> None:
        self.t = 0.0
        self.step = step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


class DrainBodyWallClockSEC1Tests(unittest.TestCase):
    """[SEC-1] Le drain d'un client lent est borne par un budget wall-clock."""

    def test_slow_drip_client_ne_retient_pas_le_thread(self) -> None:
        # Content-Length enorme (mais <= _MAX_BODY_SIZE pour ne pas tomber dans
        # l'abort 413) + flux qui ne finit jamais. Horloge factice avancant de 1s
        # par appel -> la deadline (_DRAIN_BODY_MAX_WALL_S = 10s) doit couper la
        # boucle apres ~10 iterations, PAS apres Content-Length lectures. Le fake
        # INTERDIT read() : garde-fou contre une regression vers rfile.read().
        handler = _CineSortHandler.__new__(_CineSortHandler)
        handler.headers = {"Content-Length": str(_MAX_BODY_SIZE)}
        reader = _SlowDripFakeReader()
        handler.rfile = reader
        handler.connection = _FakeConnection()
        handler._body_consumed = False

        with mock.patch.object(rest_server.time, "monotonic", _FakeClock(step=1.0)):
            handler._drain_request_body()

        # Sans le fix : reads ~ _MAX_BODY_SIZE (16M). Avec : borne par la deadline.
        self.assertLess(
            reader.reads,
            int(_DRAIN_BODY_MAX_WALL_S) + 5,
            "le drain n'est pas borne par le budget wall-clock (DoS SEC-1)",
        )
        self.assertTrue(handler._body_consumed)

    def test_client_rapide_draine_tout_avant_la_deadline(self) -> None:
        # Non-regression : un client qui envoie son body d'un bloc est draine en
        # entier (close -> FIN) ; l'horloge n'avance pas assez pour couper.
        handler = _make_handler(4, b"abcd")
        with mock.patch.object(rest_server.time, "monotonic", _FakeClock(step=0.001)):
            handler._drain_request_body()
        self.assertEqual(handler.rfile.tell(), 4, "body complet non draine")


class DrainBodyRealSocketSEC1Tests(unittest.TestCase):
    """[SEC-1] Preuve sur SOCKET REELLE : un client slow-drip via un vrai
    BufferedReader (socket.makefile) est borne et rend la main. C'est le test
    fidele au vecteur reel (le fake ne prouve que la boucle read1)."""

    def test_slow_drip_reel_est_borne_et_rend_la_main(self) -> None:
        srv, cli = socket.socketpair()
        stop = threading.Event()
        result: dict = {}

        def _drip() -> None:
            try:
                while not stop.is_set():
                    cli.sendall(b"x")
                    _time.sleep(0.2)
            except OSError:
                pass

        handler = _CineSortHandler.__new__(_CineSortHandler)
        handler.headers = {"Content-Length": str(_MAX_BODY_SIZE)}
        handler.rfile = srv.makefile("rb", -1)  # vrai BufferedReader
        handler.connection = srv
        handler._body_consumed = False

        def _run() -> None:
            t0 = _time.monotonic()
            try:
                handler._drain_request_body()
            finally:
                result["elapsed"] = _time.monotonic() - t0

        drip = threading.Thread(target=_drip, daemon=True)
        worker = threading.Thread(target=_run, daemon=True)
        try:
            # Constantes reduites pour un test rapide (budget 1s, timeout par-recv 0.5s).
            with (
                mock.patch.object(rest_server, "_DRAIN_BODY_TIMEOUT_S", 0.5),
                mock.patch.object(rest_server, "_DRAIN_BODY_MAX_WALL_S", 1.0),
            ):
                drip.start()
                worker.start()
                worker.join(timeout=5.0)
                # Regression (read() bloquant) : le worker serait encore vivant.
                self.assertFalse(
                    worker.is_alive(),
                    "le drain n'a pas rendu la main en 5s (slow-drip non borne = regression SEC-1)",
                )
                self.assertLess(
                    result.get("elapsed", 999.0),
                    3.0,
                    f"drain trop long: {result.get('elapsed')}s (budget wall-clock 1.0s)",
                )
        finally:
            stop.set()
            for s in (srv, cli):
                try:
                    s.close()
                except OSError:
                    pass
            drip.join(timeout=1.0)
            worker.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
