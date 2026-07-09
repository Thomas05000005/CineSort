# SÉCURITÉ — RÉSERVÉ À OPUS (ne pas corriger en session Fable)

> Décision utilisateur 2026-07-08 : tous les findings de sécurité de CineSort sont mis de côté
> pour être traités par Opus. Cette liste les recense (fichier:ligne + scénario) sans les corriger.

## Ouverts

### SEC-1 — Drain body pré-auth : hold de thread non authentifié (DoS)
- **Origine** : introduit par le fix BUG-LOTD-401-RST-BODY (commit `5119cac`, `_drain_request_body`).
- **Fichier** : `cinesort/infra/rest_server.py` (`_drain_request_body`, appelé dans le finally de do_POST).
- **Scénario** : un client SANS token envoie `POST Content-Length=16MB` ; le drain a un timeout de 5 s
  PAR recv mais aucun budget wall-clock total → un client lent (1 octet/4 s) tient un thread du
  serveur quasi indéfiniment sans jamais s'authentifier. Amplifiable (plusieurs connexions).
- **Fix proposé (round 1)** : deadline wall-clock totale en plus du timeout par-recv ; ou ne drainer
  qu'une quantité bornée avant close ; garder l'abort anti-DoS 413 (>16 Mo) intact.
- **Note** : le fix RST lui-même (les 401/410/404 ferment en FIN, le client Windows reçoit le JSON)
  est fonctionnel et reste en place ; c'est le durcissement anti-DoS qui est déféré.

### SEC-2 — rest_api_token stocké en CLAIR dans settings.json
- **Fichier** : `cinesort/ui/api/settings_support.py:948-949` (génération token_urlsafe) et `:1482` (persistance).
- **Scénario** : tous les autres secrets passent par DPAPI ; le token REST est généré puis conservé en
  clair (seulement masqué au GET/export) → un settings.json exfiltré donne l'accès API LAN.
- **Attention** : régression 401 historique BOM/U+FEFF — tester avec le payload UI réel.

### SEC-4 — Tuning rate-limit 401 (proposé par Thomas dans wip/b4, non appliqué)
- **Fichier** : `cinesort/infra/rest_server.py` (`_RATE_LIMIT_MAX_FAILURES = 5`).
- **Contexte** : le travail non commité de Thomas (branche `wip/b4-main-uncommitted-2026-06`)
  passait ce seuil de 5 à 20 (« FIX SAVE : éviter les faux blocages 429 en usage local quand
  l'auth hésite au boot »). C'est un ajustement d'un **contrôle de sécurité** (garde brute-force
  per-IP) → laissé à Opus. Arbitrage : 20 échecs/min/IP reste borné par le cap global (4×), mais
  desserre la protection. À valider avec le vrai comportement d'auth au boot (BOM/token gate).

### SEC-3 — Migration DPAPI-NG inachevée côté écritures ET lectures
- **Fichiers** : `cinesort/ui/api/settings_support.py:241,615,650,670-685` (écritures legacy `protect_secret`
  pour 5 secrets : TMDb, Jellyfin, Plex, Radarr, SMTP) ; lectures `:203,388,410` en `unprotect_secret`
  legacy → un blob migré en NG deviendrait illisible côté réglages.
- **Couche NG prête** : `cinesort/infra/security/secret_storage.py:81-191`, consommée uniquement par
  `poster_proxy.py:107-111`.

## Traité avant la consigne (exception, ne pas re-traiter)
- Fuite codepoints token DEBUG : corrigée E1 (`7dcf4b1`) + E1-bis (`87ca6bd`).
- Clé TMDb en clair dans le message d'erreur front (LOTD-INT-03) : corrigée `5119cac` (sanitisation
  du message, considérée fonctionnelle/fuite-info mineure, déjà livrée).

## Autres pistes sécurité de la campagne (référence, non urgentes)
- Circuit breaker absent des clients Jellyfin/Plex/Radarr (résilience, pas sécurité stricte).
- CSP : les handlers inline ont été retirés (LOTC-C1) ; RAS résiduel connu.
