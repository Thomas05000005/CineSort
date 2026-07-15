"""Tests Linux-safe du package `cinesort.infra.security`.

Le test SEC-3 (`test_sec3_dpapi_ng_migration`) ne s'execute que sous Windows
(DPAPI). Ce module couvre les invariants verifiables partout : import du
package, detection d'enveloppe NG, et contrats d'erreur quand DPAPI est
indisponible (non-Windows) ou le blob invalide.
"""

from __future__ import annotations

import base64
import os
import unittest

from cinesort.infra.security import dpapi_ng as ng
from cinesort.infra.security import secret_storage as ss


class NgBlobDetectionTests(unittest.TestCase):
    def test_ng_magic_detecte(self) -> None:
        self.assertTrue(ng.is_dpapi_ng_blob(ng._NG_MAGIC + b"payload"))

    def test_entete_dpapi_legacy_non_detecte_ng(self) -> None:
        # En-tete d'un blob DPAPI legacy : jamais confondu avec un blob NG.
        self.assertFalse(ng.is_dpapi_ng_blob(b"\x01\x00\x00\x00abcd"))

    def test_types_non_bytes_refuses(self) -> None:
        self.assertFalse(ng.is_dpapi_ng_blob("CSNGv1"))  # type: ignore[arg-type]


class SecretStorageErrorContractTests(unittest.TestCase):
    def test_load_secret_blob_vide_leve(self) -> None:
        with self.assertRaises(ss.SecretStorageError):
            ss.load_secret("tmdb_api_key", "")

    def test_load_secret_blob_illisible_leve(self) -> None:
        with self.assertRaises(ss.SecretStorageError):
            ss.load_secret("tmdb_api_key", "!!!pas-du-base64!!!")

    def test_loaded_secret_expose_value_et_scheme(self) -> None:
        loaded = ss.LoadedSecret(value="clé", scheme="dpapi_ng")
        self.assertEqual(loaded.value, "clé")
        self.assertEqual(loaded.scheme, "dpapi_ng")

    @unittest.skipIf(os.name == "nt", "Sur Windows DPAPI est disponible")
    def test_save_secret_leve_si_dpapi_indisponible(self) -> None:
        # Hors Windows, DPAPI est absent -> save_secret doit lever pour que
        # l'appelant retombe sur la protection legacy.
        with self.assertRaises(ss.SecretStorageError):
            ss.save_secret("tmdb_api_key", "valeur")

    @unittest.skipIf(os.name == "nt", "Sur Windows le legacy se dechiffre")
    def test_load_legacy_leve_si_dpapi_indisponible(self) -> None:
        legacy_b64 = base64.b64encode(b"\x01\x00\x00\x00legacy").decode("ascii")
        # Bien reconnu comme non-NG, puis routage legacy qui echoue sans DPAPI.
        self.assertFalse(ng.is_dpapi_ng_blob(base64.b64decode(legacy_b64)))
        with self.assertRaises(ss.SecretStorageError):
            ss.load_secret("tmdb_api_key", legacy_b64)


if __name__ == "__main__":
    unittest.main()
