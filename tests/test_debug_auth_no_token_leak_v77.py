# -*- coding: utf-8 -*-
"""E1 (verif totale 2026-07) : le diagnostic CINESORT_DEBUG d'un mismatch
d'auth ne doit JAMAIS logger de materiel secret.

Avant le fix, rest_server loggait la liste U+XXXX COMPLETE du token serveur
(reconstructible depuis les logs, non couverte par le log_scrubber) ainsi que
tous les codepoints du bearer. Le contrat teste ici :

 1. aucun codepoint du token serveur n'apparait dans les logs ;
 2. aucun codepoint ASCII du bearer n'apparait (un bearer quasi-correct
    reconstruirait le token) ;
 3. le diagnostic reste utile : longueurs, position de la 1ere divergence,
    codepoints NON-ASCII du bearer (cas BOM U+FEFF historique).
"""

import logging
import unittest

from cinesort.infra.rest_server import _log_auth_mismatch_debug


def _codepoints(s: str) -> list:
    return [f"U+{ord(c):04X}" for c in s]


class DebugAuthNoTokenLeakTests(unittest.TestCase):
    def _capture(self, bearer: str, token: str) -> str:
        with self.assertLogs("cinesort.infra.rest_server", level="WARNING") as cm:
            _log_auth_mismatch_debug(bearer, token)
        return "\n".join(cm.output)

    def test_token_codepoints_never_logged(self):
        token = "s3cretT0ken-urlsafe_ABC"
        out = self._capture("wrongbearer", token)
        for cp in _codepoints(token):
            self.assertNotIn(cp, out, f"codepoint du token serveur fuite dans les logs : {cp}")
        self.assertNotIn(token, out)

    def test_near_correct_bearer_not_reconstructible(self):
        # Bearer correct sauf le dernier char : AUCUN codepoint ASCII du bearer
        # ne doit sortir (sinon le log reconstruit le token a 1 char pres).
        token = "abcdefgh12345678"
        bearer = token[:-1] + "X"
        out = self._capture(bearer, token)
        for cp in _codepoints(bearer):
            self.assertNotIn(cp, out, f"codepoint ASCII du bearer fuite : {cp}")
        self.assertIn("pos=15", out)
        self.assertIn("<ascii>", out)

    def test_diagnostic_bom_preserved(self):
        # Cas racine historique : BOM U+FEFF en tete du bearer (PowerShell).
        # Le diagnostic DOIT montrer le non-ASCII du bearer et la position 0.
        token = "abcdefgh12345678"
        bearer = "﻿" + token
        out = self._capture(bearer, token)
        self.assertIn("U+FEFF", out)
        self.assertIn("pos=0", out)
        self.assertIn("bearer_len=17", out)
        self.assertIn("token_len=16", out)

    def test_non_ascii_token_never_leaks_codepoints(self):
        # E1-bis (revue Lot E) : token colle a la main, non-ASCII (é, BOM...).
        # Un bearer quasi-correct ne doit reveler AUCUN codepoint — ni du
        # token, ni de ses propres chars non-ASCII (qui sont ceux du token).
        token = "abcé£fgh"
        bearer = token[:-1] + "X"
        out = self._capture(bearer, token)
        for cp in ("U+00E9", "U+00A3"):
            self.assertNotIn(cp, out, f"codepoint du token non-ASCII fuite : {cp}")
        self.assertIn("<redacted>", out)

    def test_source_has_no_full_dump(self):
        # Garde anti-regression sur la source : les dumps historiques complets
        # ne doivent pas revenir (patterns exacts du code d'avant E1).
        import inspect

        import cinesort.infra.rest_server as mod

        src = inspect.getsource(mod)
        self.assertNotIn("server token codepoints", src)
        self.assertNotIn("bearer codepoints=", src)


if __name__ == "__main__":
    unittest.main()
