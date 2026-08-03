"""[SEC-3] Migration DPAPI legacy -> DPAPI-NG des secrets settings.

Les helpers `_protect_secret_ng` / `_unprotect_secret_ng` de settings_support
routent desormais le chiffrement des 5 secrets (TMDb, Jellyfin, Plex, Radarr,
SMTP) par la couche NG (`secret_storage`). Invariants proteges :

  1. Round-trip NG : protect_ng -> unprotect_ng redonne la valeur exacte.
  2. Le blob produit est bien un blob DPAPI-NG (magic present).
  3. RETRO-COMPAT (regle "tester base pre-existante") : un blob chiffre par
     l'ANCIEN chemin legacy (`protect_secret`) reste lisible par le NOUVEAU
     `_unprotect_secret_ng` (fallback transparent) -> pas de perte des secrets
     deja enregistres dans un settings.json existant.
  4. Les extracteurs settings (`extract_tmdb_key_from_settings_payload`) lisent
     indifferemment une enveloppe {scheme, blob_b64} portant un blob NG OU legacy.

DPAPI est specifique Windows : skip ailleurs (aligne test_local_secret_store).
"""

from __future__ import annotations

import base64
import os
import unittest

from cinesort.infra.local_secret_store import protect_secret
from cinesort.infra.security import dpapi_ng as _ng
from cinesort.ui.api.settings_support import (
    TMDB_KEY_PURPOSE,
    TMDB_KEY_SECRET_FIELD,
    WINDOWS_DPAPI_CURRENT_USER,
    _protect_secret_ng,
    _unprotect_secret_ng,
    extract_tmdb_key_from_settings_payload,
)


@unittest.skipUnless(os.name == "nt", "DPAPI specifique a Windows")
class Sec3DpapiNgMigrationTests(unittest.TestCase):
    def test_ng_roundtrip_exact(self) -> None:
        secret = "tmdb-key-éàç-2049"
        ok, blob_b64, err = _protect_secret_ng(secret, purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok, msg=f"protect_ng echoue: {err}")
        self.assertTrue(blob_b64)
        self.assertNotIn(secret, blob_b64, "secret en clair dans le blob")
        ok2, value, err2 = _unprotect_secret_ng(blob_b64, purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok2, msg=f"unprotect_ng echoue: {err2}")
        self.assertEqual(value, secret)

    def test_ecriture_produit_un_blob_ng(self) -> None:
        ok, blob_b64, _ = _protect_secret_ng("x", purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok)
        raw = base64.b64decode(blob_b64.encode("ascii"), validate=True)
        self.assertTrue(
            _ng.is_dpapi_ng_blob(raw),
            "le nouveau chemin d'ecriture doit produire un blob DPAPI-NG",
        )

    def test_blob_legacy_pre_existant_reste_lisible(self) -> None:
        # Regle memoire : tester avec un artefact PRE-EXISTANT (ancien format).
        secret = "clé-legacy-déjà-enregistrée"
        ok, legacy_blob, err = protect_secret(secret, purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok, msg=f"protect legacy echoue: {err}")
        # Preuve que c'est bien un blob LEGACY (pas de magic NG).
        legacy_raw = base64.b64decode(legacy_blob.encode("ascii"), validate=True)
        self.assertFalse(
            _ng.is_dpapi_ng_blob(legacy_raw),
            "le blob de reference doit etre legacy (sinon le test ne prouve rien)",
        )
        # Le NOUVEAU chemin de lecture doit le dechiffrer via fallback.
        ok2, value, err2 = _unprotect_secret_ng(legacy_blob, purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok2, msg=f"lecture legacy via NG echoue: {err2}")
        self.assertEqual(value, secret)

    def test_extract_tmdb_lit_enveloppe_legacy(self) -> None:
        secret = "TMDb-legacy-envelope-key"
        ok, legacy_blob, _ = protect_secret(secret, purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok)
        data = {
            TMDB_KEY_SECRET_FIELD: {
                "scheme": WINDOWS_DPAPI_CURRENT_USER,
                "blob_b64": legacy_blob,
            }
        }
        value, scheme, warning = extract_tmdb_key_from_settings_payload(data)
        self.assertEqual(value, secret)
        self.assertEqual(scheme, WINDOWS_DPAPI_CURRENT_USER)
        self.assertEqual(warning, "")

    def test_extract_tmdb_lit_enveloppe_ng(self) -> None:
        secret = "TMDb-ng-envelope-key"
        ok, ng_blob, _ = _protect_secret_ng(secret, purpose=TMDB_KEY_PURPOSE)
        self.assertTrue(ok)
        data = {
            TMDB_KEY_SECRET_FIELD: {
                "scheme": WINDOWS_DPAPI_CURRENT_USER,
                "blob_b64": ng_blob,
            }
        }
        value, scheme, warning = extract_tmdb_key_from_settings_payload(data)
        self.assertEqual(value, secret)
        self.assertEqual(scheme, WINDOWS_DPAPI_CURRENT_USER)
        self.assertEqual(warning, "")


if __name__ == "__main__":
    unittest.main()
