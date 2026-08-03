"""[SEC-2] rest_api_token chiffre au repos (plus jamais en clair sur disque).

Le token Bearer de l'API REST etait le SEUL secret stocke en clair dans
settings.json (tous les autres passaient par DPAPI). Un settings.json exfiltre
donnait donc l'acces API LAN. Il est desormais chiffre sous l'enveloppe
{scheme, blob_b64} comme les autres secrets.

Invariants proteges :
  1. Apres write, settings.json ne contient PAS le token en clair, mais une
     enveloppe `rest_api_token_secret` chiffree ; le champ clair est absent.
  2. read_settings redonne le token EN CLAIR en memoire (consomme par le boot
     du serveur REST + reveal + hot-reload) et retire l'enveloppe.
  3. MIGRATION (regle "tester base pre-existante") : un settings.json d'AVANT
     SEC-2 (rest_api_token EN CLAIR, sans enveloppe) est lu tel quel, puis migre
     au write SANS changer la valeur du token (les appareils distants deja
     apparies ne cassent pas).
  4. Token vide -> aucune enveloppe creee.

DPAPI est Windows-only : le chiffrement effectif (et donc l'absence de clair sur
disque) n'est garanti que sur nt -> skip ailleurs (comme test_local_secret_store).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.ui.api.settings_support import (
    _SECRET_MASK,
    REST_TOKEN_SECRET_FIELD,
    WINDOWS_DPAPI_CURRENT_USER,
    _mask_secrets,
    read_settings,
    write_settings,
)


class Sec2MaskOrigBlobsTests(unittest.TestCase):
    """[SEC-2 FIX-3] _mask_secrets ne doit jamais laisser fuiter un blob `_orig_*`
    (enveloppe chiffree preservee par read_settings sur echec de dechiffrement)
    sur la surface GET externe. Independant de DPAPI (teste _mask_secrets seul)."""

    def test_mask_secrets_retire_les_blobs_orig(self) -> None:
        payload = {
            "rest_api_token": "un-vrai-token-clair",
            "_orig_rest_api_token_secret": {"scheme": "x", "blob_b64": "AAAA"},
            "_orig_tmdb_api_key_secret": {"scheme": "x", "blob_b64": "BBBB"},
            "locale": "fr",
        }
        out = _mask_secrets(payload)
        self.assertNotIn("_orig_rest_api_token_secret", out)
        self.assertNotIn("_orig_tmdb_api_key_secret", out)
        # Les champs legitimes restent ; le secret reste masque.
        self.assertEqual(out.get("locale"), "fr")
        self.assertEqual(out.get("rest_api_token"), _SECRET_MASK)
        self.assertTrue(out.get("_has_rest_api_token"))


@unittest.skipUnless(os.name == "nt", "DPAPI specifique a Windows")
class Sec2RestTokenEncryptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_sec2_")
        self.state = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _settings_json(self) -> dict:
        return json.loads((self.state / "settings.json").read_text(encoding="utf-8-sig"))

    def test_token_chiffre_sur_disque_jamais_en_clair(self) -> None:
        token = "rest-secret-abc123XYZ_urlsafe-token"
        write_settings(self.state, {"rest_api_token": token, "rest_api_enabled": True})
        raw_text = (self.state / "settings.json").read_text(encoding="utf-8-sig")
        self.assertNotIn(token, raw_text, "token present EN CLAIR dans settings.json")
        raw = json.loads(raw_text)
        self.assertNotIn("rest_api_token", raw, "champ clair rest_api_token persiste")
        self.assertIn(REST_TOKEN_SECRET_FIELD, raw, "enveloppe chiffree absente")
        env = raw[REST_TOKEN_SECRET_FIELD]
        self.assertEqual(env.get("scheme"), WINDOWS_DPAPI_CURRENT_USER)
        self.assertTrue(env.get("blob_b64"))

    def test_read_settings_redonne_le_token_clair(self) -> None:
        token = "rest-secret-roundtrip-0000000000"
        write_settings(self.state, {"rest_api_token": token})
        got = read_settings(self.state)
        self.assertEqual(got.get("rest_api_token"), token)
        # L'enveloppe ne doit pas fuiter dans le dict de travail (popped).
        self.assertNotIn(REST_TOKEN_SECRET_FIELD, got)

    def test_migration_clair_preexistant_preserve_la_valeur(self) -> None:
        # settings.json d'AVANT SEC-2 : token EN CLAIR, aucune enveloppe.
        token = "legacy-clear-token-a-preserver-1234"
        (self.state / "settings.json").write_text(
            json.dumps({"rest_api_token": token, "rest_api_enabled": True}),
            encoding="utf-8",
        )
        # 1) lecture : la valeur claire est rendue telle quelle.
        got1 = read_settings(self.state)
        self.assertEqual(got1.get("rest_api_token"), token)
        # 2) ecriture (migration) : re-chiffree, valeur INCHANGEE.
        write_settings(self.state, got1)
        raw = self._settings_json()
        self.assertNotIn("rest_api_token", raw, "toujours en clair apres migration")
        self.assertIn(REST_TOKEN_SECRET_FIELD, raw)
        # 3) relecture : meme token (appareils distants preserves).
        got2 = read_settings(self.state)
        self.assertEqual(got2.get("rest_api_token"), token)

    def test_token_vide_pas_d_enveloppe(self) -> None:
        write_settings(self.state, {"rest_api_token": "", "rest_api_enabled": False})
        raw = self._settings_json()
        self.assertNotIn(REST_TOKEN_SECRET_FIELD, raw)
        self.assertNotIn("rest_api_token", raw)

    def test_double_write_reste_lisible(self) -> None:
        # Deux cycles read->write consecutifs (echo full-payload de l'UI) ne
        # doivent pas corrompre le token ni le perdre.
        token = "rest-token-double-write-cycle-999"
        write_settings(self.state, {"rest_api_token": token})
        got = read_settings(self.state)
        write_settings(self.state, got)  # re-save du payload relu
        got2 = read_settings(self.state)
        self.assertEqual(got2.get("rest_api_token"), token)


if __name__ == "__main__":
    unittest.main()
