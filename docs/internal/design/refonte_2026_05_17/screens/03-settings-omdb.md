# Spec — Paramètres > Intégrations > OMDb

Statut : **VALIDÉE** (en attente choix stratégie court/long terme).
Position dans la refonte : **Écran 3 / N**.

## Pourquoi cette spec

Test perso 2026-05-17 sur EXE v1.2.0-beta : Thomas dit "pas d'endroit où mettre la clé OMDb dans l'app, on ne sait pas si ça marche". Cf [[feedback-cinesort-ui-pacotille]].

**Diagnostic** :
- Backend OMDb **100% complet** (DPAPI + `omdb_api_key/enabled/min_confidence_for_call` dans settings + endpoint `integrations/test_omdb_connection` + intégration auto `cross_check_rows_with_omdb` après plan)
- Frontend OMDb **présent dans `web/dashboard/views/settings.js`** (dashboard ESM, lignes 157-166) avec toggle + clé + bouton test + seuil
- Frontend OMDb **ABSENT de `web/views/`** (legacy pywebview chargé par l'app native)

→ Quand Thomas lance `CineSort.exe`, c'est le legacy qui s'affiche, OMDb invisible. Le dashboard ESM est uniquement servi en mode REST (port 8642).

## 1. Layout cible (commun aux 2 frontends)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Paramètres > Intégrations                                          │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ▾ TMDb                                                              │
│     [bloc TMDb existant — inchangé]                                  │
│                                                                      │
│  ▾ Jellyfin                                                          │
│     [bloc Jellyfin existant — inchangé]                              │
│                                                                      │
│  ▾ Plex                                                              │
│     [bloc Plex existant — inchangé]                                  │
│                                                                      │
│  ▾ Radarr                                                            │
│     [bloc Radarr existant — inchangé]                                │
│                                                                      │
│  ▾ OMDb (cross-check IMDb)                                          │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                                                                │ │
│  │   ☐ Activer le cross-check IMDb                                │ │
│  │     Quand la confiance TMDb est basse, OMDb valide ou conteste │ │
│  │     le match. Convergence : +20 confidence. Désaccord : -25 +  │ │
│  │     warning sur la ligne.                                      │ │
│  │                                                                │ │
│  │   Clé API OMDb                                                 │ │
│  │   ┌──────────────────────────────────────┐  [Tester]  ✓ Valide│ │
│  │   │ ••••••••••••••••••••  [👁 Afficher]   │   Quota : 247/1000│ │
│  │   └──────────────────────────────────────┘   restant aujourd'hui│
│  │   Gratuit 1000 req/jour sur omdbapi.com/apikey.aspx ↗          │ │
│  │                                                                │ │
│  │   Seuil d'appel OMDb (confiance)                               │ │
│  │   ┌──────┐                                                     │ │
│  │   │  90  │ %                                                   │ │
│  │   └──────┘                                                     │ │
│  │   Appeler OMDb seulement si la confiance TMDb est < ce seuil.  │ │
│  │   Plus bas = moins d'appels mais moins de cross-check.         │ │
│  │                                                                │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

## 2. Source de chaque donnée et action

| UI | Backend |
|---|---|
| Toggle "Activer" | `settings.omdb_enabled` (bool, default false) |
| Champ clé (masqué par défaut, bouton 👁) | `settings.omdb_api_key` (stocké via DPAPI, jamais en clair) |
| Bouton "Tester" | `apiPost("integrations/test_omdb_connection", { api_key: "$value" })` |
| Réponse test | `{ ok: bool, message: string, quota_remaining?: int, quota_limit?: int }` |
| Indicateur "✓ Valide" / "✗ Invalide" | Couleur + texte selon `ok` |
| Affichage "Quota : 247/1000" | `quota_remaining` + `quota_limit` depuis réponse test |
| Lien externe ↗ omdbapi.com/apikey.aspx | Hard-coded, ouvre dans navigateur externe (pywebview API `open_url_external` ou `<a target="_blank">`) |
| Seuil confidence | `settings.omdb_min_confidence_for_call` (int 0-100, default 90) |

## 3. Comportement détaillé

### États du champ clé

| État | Affichage | Hint |
|---|---|---|
| Vide (jamais saisie) | placeholder "Collez votre clé OMDb..." | "Récupérez une clé gratuite sur omdbapi.com" |
| Saisie, jamais testée | clé masquée + bouton Tester actif | "Cliquez Tester pour vérifier" |
| Testée OK | clé masquée + ✓ vert + "Quota : 247/1000 restant" | "Connexion valide" |
| Testée KO (401) | clé masquée + ✗ rouge + "Clé invalide" | "Vérifiez votre clé sur omdbapi.com" |
| Testée KO (429) | clé masquée + ⚠ orange + "Quota dépassé" | "Réessayez demain ou attendez le reset minuit UTC" |
| Testée KO (réseau) | clé masquée + ⚠ orange + "Pas de réseau" | "Réseau injoignable, réessayez plus tard" |

### Persistance

- Saisie de la clé → debounce 500ms → DPAPI write côté Python
- Toggle → save immédiat
- Seuil → debounce 500ms → save
- Pattern existant `_persist_protected_secret` dans `settings_support.py` (déjà utilisé pour TMDb/Jellyfin/Plex/Radarr)

### Indicateur de quota (optionnel mais utile)

Si l'endpoint `test_omdb_connection` peut retourner le quota restant (header `X-RateLimit-Remaining` d'OMDb), on l'affiche. Sinon : juste "✓ Valide" sans quota.

Vérification du quota : à faire dans `cinesort/infra/omdb_client.py` côté Python — capter le header sur la première requête réussie.

## 4. Décision stratégique court terme vs long terme

L'OMDb est juste l'exemple visible d'un problème plus large : **le code OMDb existe dans le dashboard ESM mais pas dans le legacy pywebview**. Cela vaut probablement pour d'autres fonctions ajoutées récemment.

### Option A — Court terme : porter OMDb dans le legacy aussi

**Effort** : ~0.5 j
**Risque** : faible

```
1. Copier le bloc OMDb (lignes 157-166) de
   web/dashboard/views/settings.js
   vers
   web/views/settings-v5.js (ou settings.js)
2. Vérifier que le testMethod "integrations/test_omdb_connection"
   marche aussi via pywebview API (probablement OK car le mapping
   apiPost("X/Y") → pywebview.api.X_Y existe)
3. Tests E2E + manuel
```

→ Débloque Thomas immédiatement, mais **maintient la duplication legacy/dashboard** que tous les audits dénoncent (#91, #217, etc.).

### Option B — Long terme : décommissionner le legacy, faire pywebview charger le dashboard ESM

**Effort** : ~3-5 j (issue #217)
**Risque** : moyen (~349 tests v5 à adapter)

```
1. Modifier app.py pour que pywebview charge web/dashboard/index.html
   au lieu de web/index.html (1 ligne de code)
2. Adapter les ~349 tests v5 qui dépendent du legacy
3. Tester que toutes les vues fonctionnent en pywebview natif
4. Supprimer web/views/ + web/components/ + web/index.html
```

→ Plus propre architecturalement, fait gagner ~5645 lignes de CSS et 26 composants legacy. Mais ce n'est pas la spec OMDb, c'est la spec "tuer le legacy".

### Option C — Solution intermédiaire : porter OMDb maintenant, planifier B après

Considérée mais **rejetée** : ajoute 0.5 j de travail jeté (le port OMDb dans le legacy sera supprimé avec le legacy) sans bénéfice réel (Thomas est en phase SPEC, pas usage opérationnel).

### ✅ CHOIX FINAL — Option B (migration directe vers ESM)

Validé par Thomas le 2026-05-17 après comparaison B vs C.

- Pas de port OMDb dans le legacy.
- On va directement à la migration `legacy → dashboard ESM` (3-5 j).
- OMDb sera dispo dans l'app native dès que pywebview chargera le dashboard ESM (la section OMDb existe déjà dans `web/dashboard/views/settings.js` lignes 157-166).

**Conséquence pour les specs suivantes (écrans 4 à N)** : on les rédige uniquement pour cibler `web/dashboard/`. Aucun double portage.

**Effort OMDb dans le scope final** : ~0 j additionnel — c'est inclus dans la migration B (la section frontend existe, il faut juste éventuellement ajouter `quota_remaining` dans la réponse `test_omdb_connection` côté Python, soit 0.2 j marginal).

## 5. Effort estimé (option A retenue par défaut)

| Tâche | Effort |
|---|---|
| Frontend : copier bloc OMDb (3 champs) du dashboard ESM vers legacy | 0.2 j |
| Frontend : tester `apiPost("integrations/test_omdb_connection")` côté pywebview | 0.1 j |
| Backend : ajouter `quota_remaining` dans réponse `test_omdb_connection` (capter X-RateLimit-Remaining) | 0.2 j |
| Tests E2E | 0.1 j |
| **Total OMDb (option A)** | **~0.5 jour** |

## 6. Hors scope v1

- ❌ Historique d'appels OMDb (futur, si besoin de debug)
- ❌ Quota total cumulé sur N jours (juste le quota d'aujourd'hui suffit pour v1)
- ❌ Configuration du timeout OMDb (default 10s suffit)
- ❌ Cache OMDb avec TTL configurable (utilise déjà un cache permanent côté backend)
