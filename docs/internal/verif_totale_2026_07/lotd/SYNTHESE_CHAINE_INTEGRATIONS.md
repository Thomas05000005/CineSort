# Lot D — Chaîne 4.5 INTEGRATIONS (Jellyfin / Radarr / TMDb) — 2026-07-08

Test permanent : `tests/test_lotd_chain_integrations.py` (14 tests).
Pilotage : `CineSortApi.integrations` direct + `jellyfin_sync.restore_watched` avec un
`JellyfinClient` réel contre des mocks `http.server` locaux (ports éphémères,
`tests/_helpers.find_free_port`, aucun réseau externe, aucun chemin hors tempdir).
Stabilité : 2 runs consécutifs identiques — **11 passed + 3 xfail nominatifs, ~64 s**
(preuve : `pytest_integrations_run2.txt`).

## Scénarios joués

1. **test_connection OK / erreur propre** : Jellyfin (200 → ok + server_name/user_id/libs/count)
   et Radarr (200 → ok + version) ; port fermé → `ok=False` + message propre, pas d'exception.
   Bonus : `get_jellyfin_libraries` non configuré → réponse métier propre.
2. **Retries** : GET `/System/Info/Public` 503→200 **re-tenté** par la session
   (`make_session_with_retry`, preuve positive ≥2 hits). POST `/PlayedItems` 503→200 :
   **R8-080 confirmé** (voir findings).
3. **Timeouts** : mock qui dort 2 s, `timeout_s=1` → erreur bornée (~8 s à cause des
   3 retries de session + backoff, borne 30 s), pas de hang ; le message mentionne bien
   le timeout (LOTD-INT-02 **non confirmé** → pas de finding).
4. **Secrets** : scrubber prod installé (comme app.py au boot), capture root DEBUG,
   3 tokens mock (Jellyfin/Radarr/TMDb) jamais en clair dans les **logs** ; toute
   occurrence `api_key=` dans les logs est `[REDACTED]`. En revanche le **message
   frontend** de test_tmdb_key leake la clé (LOTD-INT-03).
5. **TMDb sans réseau réel** : clé vide → erreur de validation ; clé bidon +
   `TMDB_API_BASE` monkeypatché vers un port local fermé → erreur propre ;
   `get_tmdb_posters` sans clé → `ok=True, posters={}, reason=tmdb_not_configured`.

## Findings (figés en gardes xfail nominatives dans le test)

| ID | Sév. | Symptôme | Preuve |
|----|------|----------|--------|
| **R8-080** | HIGH | Flag « vu » Jellyfin PERDU sur hoquet transitoire : `mark_played` (POST) reçoit 503 → compté en `errors` et retiré de `pending`, jamais re-tenté. Aucune couche ne re-tente : POST exclu de `allowed_methods` du retry de session (`_http_utils.py:15`) ET `restore_watched` ne re-pende pas les échecs (`jellyfin_sync.py:225-246`). | mock 503 puis 200 : `restored=0, errors=1`, exactement **1** POST reçu (un 2e aurait réussi) |
| **LOTD-INT-01** | HIGH | La boucle retry H-11 de `restore_watched` ne catch que `(ConnectionError, OSError, TimeoutError, ValueError)` (`jellyfin_sync.py:205`) : `JellyfinError` (levée par le client sur tout HTTP 4xx/5xx épuisé) s'échappe → **toute** la restauration des flags « vu » est abandonnée au lieu de consommer une tentative. Rattrapée plus haut par `apply_support._restore_jellyfin_watched` (log WARN) mais les statuts sont perdus. | mock : 1er GET `/Items` → 404 puis 200 : `JellyfinError("Erreur HTTP 404...")` propagée hors de `restore_watched` (au lieu de `restored=1` à la tentative 2) |
| **LOTD-INT-03** | MED | `test_tmdb_key` en échec réseau renvoie au frontend `"Erreur reseau: {exc}"` où l'exception requests contient l'URL complète `...?api_key=<clé en clair>` — contraire à la politique repo (`_safe_integration_error`, « ne pas leak exc string »). Les logs, eux, sont bien caviardés par le scrubber. | clé mock présente en clair dans `res["message"]` (endpoint local fermé, zéro réseau externe) |

## Limites

- **Plex/OMDb/SMTP non couverts** (hors périmètre 4.5 demandé : Jellyfin/Radarr/TMDb).
- **TMDb clé bidon** : pour respecter « pas de vrai réseau », la branche 401 TMDb réelle
  n'est pas jouée ; on couvre la branche erreur réseau via `TMDB_API_BASE` → port local fermé.
- Pas de binaire externe requis par cette chaîne (aucun ffprobe/mediainfo impliqué).
- Le coût ~64 s vient des 2 tests timeout (retries de session ×4 + backoff 3,5 s) et des
  retries sur ports fermés — intrinsèque au comportement prod mesuré.
