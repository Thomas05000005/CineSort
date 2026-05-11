"""Phase 3 v7.8.0 — tests directs pour `cinesort.infra.local_secret_store`.

Le module local_secret_store.py protege via Windows DPAPI les secrets
sensibles (tmdb_api_key, jellyfin_api_key, plex_token, radarr_api_key,
email_smtp_password). Il etait identifie comme module sans test direct
malgre son role critique (audit v7.7.0+).

Couvre :
- protection_available() retourne True sur Windows nt, False ailleurs
- protect_secret/unprotect_secret round-trip pour valeurs typiques
- UTF-8 multi-byte preserve (accents, emojis, japonais)
- Long secrets (>256 octets) preserves
- Entropy (purpose) lie au blob : decoder avec autre purpose echoue
- Blob base64 invalide → echec propre, pas de crash
- Valeur vide → tolere
- Plusieurs purposes distincts : isolation cryptographique
"""
from __future__ import annotations

import os
import unittest

from cinesort.infra.local_secret_store import (
    protect_secret,
    protection_available,
    unprotect_secret,
)


@unittest.skipUnless(os.name == "nt", "DPAPI specifique a Windows")
class DPAPIRoundTripTests(unittest.TestCase):
    """Verifie que protect→unprotect retourne la valeur originale."""

    def test_protection_available_on_windows(self) -> None:
        self.assertTrue(protection_available())

    def test_simple_ascii_roundtrip(self) -> None:
        secret = "my-secret-token-1234"
        ok, blob, err = protect_secret(secret, purpose="tmdb_api_key")
        self.assertTrue(ok, msg=f"protect echoue: {err}")
        self.assertTrue(blob)
        self.assertNotIn(secret, blob, "le blob ne doit pas contenir le secret en clair")

        ok2, recovered, err2 = unprotect_secret(blob, purpose="tmdb_api_key")
        self.assertTrue(ok2, msg=f"unprotect echoue: {err2}")
        self.assertEqual(recovered, secret)

    def test_utf8_accents_roundtrip(self) -> None:
        secret = "clé-de-prod-éàüç"
        ok, blob, _ = protect_secret(secret, purpose="jellyfin_api_key")
        self.assertTrue(ok)
        ok2, recovered, _ = unprotect_secret(blob, purpose="jellyfin_api_key")
        self.assertTrue(ok2)
        self.assertEqual(recovered, secret)

    def test_utf8_emoji_roundtrip(self) -> None:
        secret = "🎬 CineSort 🔐 v7.8.0"
        ok, blob, _ = protect_secret(secret, purpose="email_smtp_password")
        self.assertTrue(ok)
        ok2, recovered, _ = unprotect_secret(blob, purpose="email_smtp_password")
        self.assertTrue(ok2)
        self.assertEqual(recovered, secret)

    def test_long_secret_roundtrip(self) -> None:
        secret = "x" * 4096
        ok, blob, _ = protect_secret(secret, purpose="plex_token")
        self.assertTrue(ok)
        ok2, recovered, _ = unprotect_secret(blob, purpose="plex_token")
        self.assertTrue(ok2)
        self.assertEqual(recovered, secret)

    def test_empty_secret_protection_is_rejected_cleanly(self) -> None:
        # DPAPI ne protege pas une valeur vide ; le module renvoie un echec
        # propre plutot qu'un crash. Les callers (settings_support) doivent
        # detecter et ne pas tenter de proteger un champ vide.
        ok, blob, err = protect_secret("", purpose="radarr_api_key")
        self.assertFalse(ok)
        self.assertEqual(blob, "")
        self.assertTrue(err)


@unittest.skipUnless(os.name == "nt", "DPAPI specifique a Windows")
class DPAPIEntropyIsolationTests(unittest.TestCase):
    """Verifie l'isolation cryptographique via le parametre purpose."""

    def test_wrong_purpose_fails_decryption(self) -> None:
        secret = "isolated-secret-42"
        ok, blob, _ = protect_secret(secret, purpose="tmdb_api_key")
        self.assertTrue(ok)
        # Tentative avec mauvais purpose : DPAPI doit refuser
        ok2, recovered, err = unprotect_secret(blob, purpose="jellyfin_api_key")
        self.assertFalse(ok2, msg="unprotect avec mauvais purpose devrait echouer")
        self.assertEqual(recovered, "")
        self.assertTrue(err, "un message d'erreur doit etre renvoye")

    def test_each_purpose_yields_distinct_blob(self) -> None:
        secret = "same-secret"
        _, blob_a, _ = protect_secret(secret, purpose="tmdb_api_key")
        _, blob_b, _ = protect_secret(secret, purpose="plex_token")
        # Meme valeur, deux purposes : les blobs doivent differer
        self.assertNotEqual(blob_a, blob_b)


@unittest.skipUnless(os.name == "nt", "DPAPI specifique a Windows")
class DPAPIInvalidInputTests(unittest.TestCase):
    """Verifie la robustesse aux entrees malformees."""

    def test_invalid_base64_blob(self) -> None:
        ok, recovered, err = unprotect_secret("ce-n-est-pas-du-base64-!@#", purpose="tmdb_api_key")
        self.assertFalse(ok)
        self.assertEqual(recovered, "")
        self.assertTrue(err)

    def test_valid_base64_but_not_dpapi_blob(self) -> None:
        # base64 valide mais payload qui n'est pas un blob DPAPI
        ok, recovered, err = unprotect_secret("aGVsbG8gd29ybGQ=", purpose="tmdb_api_key")
        self.assertFalse(ok)
        self.assertEqual(recovered, "")
        self.assertTrue(err)

    def test_empty_blob_fails_cleanly(self) -> None:
        ok, recovered, err = unprotect_secret("", purpose="tmdb_api_key")
        self.assertFalse(ok)
        self.assertEqual(recovered, "")
        # Pas de crash — c'est l'essentiel


class DPAPIPlatformGuardTests(unittest.TestCase):
    """Verifie le comportement hors Windows (skip pas nt)."""

    @unittest.skipIf(os.name == "nt", "Test hors-Windows uniquement")
    def test_protection_unavailable_off_windows(self) -> None:
        self.assertFalse(protection_available())
        ok, blob, err = protect_secret("anything", purpose="tmdb_api_key")
        self.assertFalse(ok)
        self.assertEqual(blob, "")
        self.assertIn("DPAPI", err)


if __name__ == "__main__":
    unittest.main()
