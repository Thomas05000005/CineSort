# SYNTHÈSE LOT E — Corrections rapides + revue adversaire 2 rounds — 2026-07-08

> Branche `verif/totale-2026-07`, commits `7dcf4b1..d6aa565` (14 commits).
> **KNOWN_BROKEN du contrat M1 = {} : toute violation UI→API est désormais bloquante.**
> Vérif finale : contrats + gates 164 passed (4 échecs = baseline préexistante), import-linter 3/3.

## Les 8 correctifs initiaux (E1-E8)

| # | Commit | Correctif | GATE |
|---|---|---|---|
| E1 | `7dcf4b1` | Fuite codepoints token DEBUG → `_log_auth_mismatch_debug` sans matériel secret | test_debug_auth_no_token_leak_v77 (4 tests) |
| E2 | `c9b1a1b` | Bouton Ignorer (traitement) → `library/mark_alert_ignored` par alert_code | contrat M1 |
| E3 | `b8e9176` | Ouvrir dossier → bridge pywebview natif (exclusion REST conservée), bouton masqué hors desktop | contrat M1 |
| E4 | `481fa86` | `force_refresh` get_tmdb_posters câblé bout-en-bout | test_tmdb_force_refresh_v77 |
| E5 | `d2fe519` | Bouton Apply /processing : payload conforme + dangerConfirmModal | contrat M1 |
| E6 | `35490dc` | cancel-run : confirmation + feedback réel (catch mort) | node --check |
| E7 | `fadc412` | R8-083 : unmountProcessing câblé au router | — |
| E8 | `c3d6375` | radarr_movie_id + KNOWN_BROKEN vidée | contrat M1 |

## Revue adversaire round 1 (3 lentilles → 17 findings → 10 CONFIRMÉS, 4 NUANCÉS, 3 RÉFUTÉS)

Corrections (6 commits `087ee06..87ca6bd` + E3-bis) :
- **E5-bis (HIGH ×3 lentilles)** : `decisions:{}` = reject-all sur run non validé (quarantaine de
  masse si case cochée, faux succès sinon). → décisions de l'écran autoritaires,
  `_ensureDecisionsLoaded`, garde 0-approuvé → renvoi vers Review, modale avec compte réel,
  `_saveDecisions` signale ses échecs.
- **E2-bis (MED ×3)** : l'alerte ignorée ré-apparaissait à chaque reload — `run/get_plan` servait les
  warning_flags bruts. → `list_ignored_alerts_bulk` (1 requête/chunk 500) + `_subtract_ignored_flags`
  sur les 2 branches. GATE test_get_plan_ignored_alerts_v77.
- **E7-bis (MED)** : tick get_status en vol ressuscitait le poll après unmount → compteur `pollGen`.
- **E7-ter (LOW)** : cleanup /processing retourné en synchrone (course `_currentCleanup` du router).
- **E4-bis (MED+LOW)** : bust du proxy poster (sinon l'image fraîche revenait à l'ancienne au
  re-render) + bypass de lecture au lieu de purge (le fallback stale survit si TMDb down).
- **E1-bis (MED)** : garde `isascii()` — un token collé à la main peut être non-ASCII, ses codepoints
  ne sortent plus.
- **E3-bis (LOW)** : re-render au `pywebviewready` (bouton Ouvrir dossier fiable si fiche rendue
  avant l'injection du bridge).

## Revue adversaire round 2 (sur les correctifs du round 1 → 2 CONFIRMÉS, corrigés)

- **R2-décisions (HAUTE)** `0e4ba4d` : `_state.decisions` survivait au changement de run — la garde
  0-approuvé comptait les approbations du run PRÉCÉDENT (quarantaine de masse possible sur le
  nouveau run). → `decisionsRunId` propriétaire + reset à chaque scan.
- **R2-sqlite (MOYENNE)** `d6aa565` : `sqlite3.Error` n'hérite pas d'OSError — un « database is
  locked » faisait échouer `get_plan` entier au lieu du best-effort documenté. → tuples élargis
  (+RuntimeError), GATE dédié.

**Leçon (validée 2 fois)** : la règle « 2-3 rounds find→verify avant de clore » attrape des bugs
réels À CHAQUE round — y compris dans les correctifs du round précédent. À conserver pour tous les
lots de la campagne.

## État du backlog après Lot E

- Boutons cassés M1 : **5/5 corrigés** (KNOWN_BROKEN vide).
- R8 résiduels : R8-083 **soldé** (et durci) ; restent R8-084→déjà corrigé dans R8 (constat M8),
  R8-085 (saga mkdir), 4 LOW, différés actés.
- Sécurité : fuite token DEBUG **soldée** (2 passes). Restent : rest_api_token en clair, DPAPI-NG.
- La vue /processing reste legacy (redondante avec traitement) — candidate à la purge/fusion en
  Phase 5 principale, mais elle est maintenant SÛRE (payload conforme, confirmations, polls propres,
  décisions liées au run).

## Suite

Lot C (Phase 3 runtime Playwright, 13 vues) — les corrections de ce lot évitent au gate
« console 0 erreur » de re-découvrir 5 boutons cassés connus.
