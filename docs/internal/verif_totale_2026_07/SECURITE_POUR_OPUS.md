# SÉCURITÉ — TRAITÉE PAR OPUS (session 2026-07-10)

> Décision utilisateur 2026-07-08 : tous les findings de sécurité de CineSort étaient mis de côté
> pour Opus. **Session Opus 2026-07-10 : les 4 items sont traités** (branche `security/opus-2026-07`),
> chacun avec un GATE de test + revue adversaire (3 agents) qui a attrapé 2 vrais bugs DANS la 1re
> passe (voir « Revue adversaire » ci-dessous). Statuts ci-dessous : ✅ = résolu.

## Traités

### ✅ SEC-1 — Drain body pré-auth : hold de thread non authentifié (DoS)
- **Fichier** : `cinesort/infra/rest_server.py` (`_drain_request_body`).
- **Scénario** : un client SANS token envoie `POST Content-Length` gros ; le timeout de 5 s est PAR
  recv, sans budget wall-clock total → un client lent (1 octet/4 s) tient un thread quasi indéfiniment.
- **Fix livré** : budget wall-clock TOTAL `_DRAIN_BODY_MAX_WALL_S=10s` + lecture par `read1()` (au plus
  un recv → la boucle re-teste la deadline) + timeout par-recv borné par le budget restant. L'abort
  anti-DoS 413 (>16 Mo) et les early-returns restent intacts.
- **NB revue** : la 1re passe (deadline testée en haut de boucle + `rfile.read()`) était **INEFFICACE**
  — `read()` sur un `BufferedReader` boucle des recv() sans rendre la main. Corrigé (read1). GATE :
  `tests/test_rest_drain_body_lotd.py` (fake interdisant read() + test sur socket réelle slow-drip).

### ✅ SEC-2 — rest_api_token stocké en CLAIR dans settings.json
- **Fichiers** : `cinesort/ui/api/settings_support.py` (`read_settings`/`write_settings`, constantes
  `REST_TOKEN_SECRET_FIELD`/`REST_TOKEN_PURPOSE`), `cinesort/ui/api/export_support.py`, `app.py`.
- **Scénario** : seul secret en clair → un settings.json exfiltré donnait l'accès API LAN.
- **Fix livré** : token chiffré au repos sous l'enveloppe `rest_api_token_secret` (comme les autres
  secrets). `read_settings` déchiffre → token clair en mémoire (boot serveur REST + reveal +
  hot-reload) ; `write_settings` re-chiffre ; `_mask_secrets` masque au GET. Migration : un token
  clair pré-existant est lu tel quel puis chiffré au 1er save, **valeur inchangée** (appareils
  distants préservés). Enveloppe exclue de l'export.
- **NB revue** : la 1re passe cassait le **boot desktop** (`app.py:_start_rest_server` lisait le token
  clair du JSON brut → vide → masque → bind LAN rétrogradé). Corrigé (FIX-2) : token résolu via
  `api._internal_settings()` (déchiffré). Caveat `_orig_*` non masqué au GET → corrigé (FIX-3).
- **FIX-4 (2e passe revue)** : bug PRÉ-EXISTANT de même classe dans le boot **headless** `app.py --api`
  (`main_api`) — il lisait `token = get_settings()["rest_api_token"]` = MASQUE → bearer = constante
  publique devinable, garde `if not token` mort, bind LAN rétrogradé sous `--public`. Corrigé pareil
  (token via `_internal_settings()`, pas de mint en headless : refuse de démarrer sans token).
- **GATE** : `tests/test_sec2_rest_token_encryption.py`, `tests/test_sec2_boot_token.py`.

### ✅ SEC-3 — Migration DPAPI legacy → DPAPI-NG des 5 secrets
- **Fichier** : `cinesort/ui/api/settings_support.py` (adaptateurs `_protect_secret_ng`/
  `_unprotect_secret_ng` routant par `secret_storage`, 6 sites d'appel).
- **Fix livré** : écriture TOUJOURS NG ; lecture NG ou legacy (fallback transparent) → rétro-compat
  totale (blobs legacy existants toujours lisibles), migration effective au prochain save. Enveloppe
  `{scheme, blob_b64}` inchangée. GATE : `tests/test_sec3_dpapi_ng_migration.py` (round-trip NG +
  blob legacy pré-existant). Revue : NO BUG.

### ✅ SEC-4 — Tuning rate-limit 401 : proposition 5→20 REJETÉE (décision Opus)
- **Fichier** : `cinesort/infra/rest_server.py` (`_RATE_LIMIT_MAX_FAILURES = 5`, gardé).
- **Décision** : la cause racine des faux 429 locaux est déjà traitée à la source — IPs locales
  TOTALEMENT exemptées (`_is_rate_limited`) + 401 sans Bearer non comptés (`_has_bearer_header`). Le
  seuil ne s'applique qu'aux IPs **distantes** où 5/60s est la protection brute-force voulue. Monter
  à 20 ne gagnerait rien en local (déjà exempté) et affaiblirait la seule surface réelle. Décision
  documentée dans le code + confirmée par la revue adversaire.

## Revue adversaire (session 2026-07-10)
- **1re passe (3 agents)** : a attrapé **2 vrais bugs** — SEC-1 drain inefficace (`read()` bloque sur
  un `BufferedReader`) + SEC-2 boot desktop cassé (masque). SEC-3, SEC-4 et le reste de SEC-2 sains.
- **2e passe (3 agents, verify FIX-1/2/3)** : FIX-1/2/3 confirmés **SOUND** (FIX-1 prouvé empiriquement
  sur socket réelle : drain rendu en ~1 s pour un budget 1 s). A trouvé **1 bug pré-existant** de la
  même classe → **FIX-4** (boot headless `--api`).
- **Bilan** : 3 vrais bugs corrigés AVANT tout tag/push — aucun n'a atteint le main public. La règle
  « revue adversaire avant clôture » a payé à chaque passe. Total GATE : 25 tests SEC dédiés verts,
  `test_rest_security` 18/18, import-linter 3/3, contrats 25/25, 0 nouvelle régression.

## Traité avant la consigne (exception, ne pas re-traiter)
- Fuite codepoints token DEBUG : corrigée E1 (`7dcf4b1`) + E1-bis (`87ca6bd`).
- Clé TMDb en clair dans le message d'erreur front (LOTD-INT-03) : corrigée `5119cac` (sanitisation
  du message, considérée fonctionnelle/fuite-info mineure, déjà livrée).

## Autres pistes sécurité de la campagne (référence, non urgentes)
- Circuit breaker absent des clients Jellyfin/Plex/Radarr (résilience, pas sécurité stricte).
- CSP : les handlers inline ont été retirés (LOTC-C1) ; RAS résiduel connu.
