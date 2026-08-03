# DIAG POSTERS - CineSort - 2026-06-08

> Mission: DIAGNOSTIC SEUL, AUCUN fix.
> Branche: loop/correction-2026-06
> Checkpoint: f493abdc

## EN TETE - VERDICT DIAGNOSTIC

### Cause classee

- [ ] (i) HARNESS — **NON RETENU**. Le harness `scripts/_iter2_scan.py` a bien scanne les 2 bons roots (`test_library/RootA` + `RootB`, cf section 1.5), le scan est alle au bout (`status=DONE` en 12.4s, section 1.3), et `observe.py` n'a PAS contourne l'injection `?ntoken=...` (la pywebview ouverte par subprocess passe par `app.py` L819-L832 comme un boot normal, section 2.3). La seule erreur harness est un `UnicodeEncodeError` cp1252 dans `print()` POST-scan (section 1.4), sans impact backend. [FIGE]
- [X] (ii) PRODUIT scan/probe — **RETENU comme cause principale**. Court-circuit du pipeline d'enrichissement TMDb : parse local OK (`confidence=high`, titre extrait) mais 0/20 items aboutissent a un `tmdb_id` ou `poster_url` non-null dans `plan.jsonl` (section 1.6). Aucune trace d'appel HTTP TMDb dans les logs applicatifs disponibles (section 1.7). Comme la section 4 a prouve que le client TMDb fonctionne (cle valide, DPAPI OK, `/search/movie` repond 200 avec `poster_path` non-null), le defaut est en amont : `TmdbClient.search_movie` n'est PAS invoque par le pipeline scan, OU son resultat est jete au mapping vers `plan.jsonl`. [HYPOTHESE FORTE]
- [X] (iii) PRODUIT token — **RETENU comme bruit non bloquant**. Cas MIXTE B.3 dominant (seed `settings.json` du harness sans `rest_api_token`, race possible avec la regen au boot) + B.1 secondaire (token rejete par `_URLSAFE_TOKEN_RE` si caractere non-urlsafe survit au strip BOM de `app.py` L798). Consequence reelle : **NULLE** — le bypass localhost `_check_auth` (`rest_server.py` L433-L464) absorbe l'absence de Bearer (client `127.0.0.1` + bind `127.0.0.1` + pas de `CINESORT_DISABLE_LOCAL_AUTH`). Les fetchs API repondent 200 et le chargement bibliotheque/poster TMDb cote backend n'est PAS bloque (section 2.6-2.7). [FIGE]
- [ ] (iv) PRODUIT CSP-rendu — **NON RETENU comme cause**. 16 violations recensees, 100% `style-src-attr` / `blockedURI="inline"`, exclusivement sur les `<div class="v5-skeleton" style="height:64px;margin:8px 0;">` des loaders dans `bibliotheque.js:562`, `doublons.js`, `traitement.js`. Le moteur de rendu de la grille (`_renderFilmCard` L397-446) utilise des classes CSS, pas de `style="..."` inline, et `<img class="bibliotheque-card-poster-img" src="...">` n'est pas filtre par `style-src-attr`. Effet : cosmetique sur les squelettes, AUCUN impact sur la grille reelle ni sur le chargement poster. Les 13 vues SANS violation CSP ont le meme verdict `POSTERS_ABSENTS` que les 4 vues AVEC violation (section 3.5). [FIGE]
- [ ] (v) PRODUIT cle TMDb — **ELIMINE en section 4**. Sonde live executee : DPAPI `unprotect_secret(purpose=TMDB_KEY_PURPOSE)` reussit sans warning, cle clair = 32 caracteres (format TMDb v3 valide), `TmdbClient.search_movie("Inception", year=2010)` repond 200 avec 3 candidats valides, `poster_path` non-null pour les 3, et le detail `_get_movie_detail_cached(27205)` retourne aussi un `poster_path`. Aucun 401/403/429/timeout/CircuitOpenError. La cle est valide, dechiffrable, fonctionnelle. [FIGE]

### LAQUELLE BLOQUE EN PREMIER

**Cause (ii) PRODUIT scan/probe** — pipeline court-circuite l'invocation de `TmdbClient.search_movie` lors du `start_plan`.

Preuve (fait dur) :
- `plan.jsonl` (section 1.6) : 20/20 rows avec `tmdb_id=None` ET `poster_url=None`, alors que le parse local renvoie `confidence=high` sur le titre `Big Buck Bunny`. Si TMDb avait ete appele, on aurait au moins quelques `tmdb_id` (le parser confiant doit deboucher sur une recherche). [FIGE]
- Aucune trace `cinesort.infra.tmdb_client` (search, http, cache miss/hit) dans la tail applicative fournie [HYPOTHESE — fenetre hors run].
- Section 4 a prouve que TMDb repond 200 sur la cle live : ce n'est donc PAS un echec reseau ou un 401 silencieux qui mange les resultats.
- Le bypass localhost (cause iii, section 2.6) absorbe l'absence de token donc cause (iii) n'a aucun effet bloquant en amont. Cause (iv) ne touche que les skeletons (section 3.4). Cause (v) eliminee (section 4.6). Cause (i) refutee (section 1.3-1.5 + 2.3).
- Seule cause qui produit exactement le symptome `rows with tmdb_id : 0` + `rows with poster : 0` : enrichissement TMDb non invoque cote backend pendant le scan.

Pour voir des URLs TMDb dans le DOM, il faut **d'abord** que `tmdb_id` et `poster_url` soient persistes dans `plan.jsonl` cote backend. Tant que la cause (ii) est en place, le frontend ne pourra **jamais** rendre des `<img>` poster, quelle que soit la levee des causes (iii), (iv).

### Statut token (harness vs produit)

**MIXTE** — bug PRODUIT confirme, mais bruit console NON bloquant.

- **Cas A artefact harness REJETE** : `observe.py` lance `app.py` (ou `dist/CineSort.exe`) en subprocess et c'est `app.py` L819-L832 qui construit l'URL avec `?ntoken=...&native=1` ; le harness ne contourne PAS cette injection.
- **Cas B vrai bug produit RETENU** :
  - **B.3 (dominant)** : seed `settings.json` ecrit par `observe.py` L227-L238 ne contient pas `rest_api_token`. Au boot, `apply_settings_defaults` regenere un token aleatoire, mais une race possible avec `_start_rest_server` L308-L347 fait que `rest_server._token` peut etre vide au moment de la construction de `main_url`. Dans ce cas, `app.py` L840-L842 log `[REST] AVERTISSEMENT : main_url SANS ntoken`. [HYPOTHESE forte]
  - **B.1 (secondaire)** : si un caractere non-urlsafe (BOM U+FEFF, em-dash) survit au `strip().replace("﻿","")` de `app.py` L798, `setToken` (`state.js` L48-L70) rejette silencieusement le token, ne fait pas `markTokenReady`, le gate `awaitToken()` deadline a 2s, et `getToken()` rend `""`. [HYPOTHESE moyenne]
- **Consequence reelle** : **NULLE** sur la fonctionnalite. Le bypass localhost (`rest_server.py` L433-L464) renvoie 200 aux fetchs locaux meme sans Bearer. Le symptome `0 posters` (section 1.6) **n'est PAS cause par cette absence de token frontend** ; il a une autre origine (cause (ii) ci-dessus).

### Ce que bloquent les violations CSP non-tmdb

16 violations, toutes `blockedURI="inline"` / `violatedDirective="style-src-attr"`, reparties sur 4 vues (`traitement_step_verification` x3, `traitement_step_doublons` x3, `bibliotheque` x5, `doublons` x5).

| Element bloque | Source | Effet visible | Criticite |
|---|---|---|---|
| 5x `<div class="v5-skeleton" style="height:64px;margin:8px 0;">` (loaders bibliotheque) | `web/dashboard/views/bibliotheque.js:562` | Les 5 lignes squelette perdent leur silhouette (height + margin) avant le remplacement par la grille reelle | **Cosmetique** — n'affecte pas la grille finale (classes CSS uniquement) |
| 5x meme pattern dans `doublons.js` | `web/dashboard/views/doublons.js` | Squelettes doublons sans silhouette | **Cosmetique** |
| 3x meme pattern dans `traitement.js` (2 vues x 3) | `web/dashboard/views/traitement.js` | Squelettes etapes traitement sans silhouette | **Cosmetique** |

**Aucune des 16 violations** ne touche :
- `script-src` (le JS de la grille tourne normalement)
- `img-src` (les `<img src="https://image.tmdb.org/...">` ne sont pas bloques par CSP — si jamais ils etaient rendus)
- `style-src-elem` (les `<style>` blocks)
- `connect-src` (les fetchs `/api/...` et `/api/library/tmdb_proxy/...`)
- Un domaine externe (toutes les violations sont `inline`, source-keyword)

**Criticite globale** : dette technique cosmetique a nettoyer en passe ulterieure, **HORS scope** du symptome POSTERS_ABSENTS.

### Racine commune SMB (probe non resilient)

**NON.**

Preuves :
- Les roots scannes sont sur **filesystem local NTFS** : `C:\Users\blanc\projects\CineSort\test_library\RootA` et `test_library\RootB` (section 1.5, log `_scan_run.log` L18, L24-L26). Aucun UNC `\\server\share\...`, aucun mount SMB.
- Le scan est alle au bout sans hang en 12.4s (section 1.3-1.4). Si un cluster probe SMB etait non resilient, on attendrait soit un timeout, soit un freeze sur un fichier, soit une erreur reseau. Aucune des trois n'apparait dans les logs.
- Aucune erreur de type `OSError`, `WinError 64/53/67`, `ConnectionResetError`, `smb`, ou stacktrace probe (`ffprobe` / `mediainfo`) n'est presente dans `_scan_run.log` ni `cinesort.log.tail.txt`.
- Le profil SQLite `nas_smb` ou `nas_smb_slow` (`infra/db/pragma_profile.py`, VO-A) n'est PAS reference dans les logs : aucun message `pragma_history` ne signale une bascule vers un profil SMB.
- Le symptome `rows with tmdb_id : 0` est present meme sur le filesystem local : l'enrichissement TMDb echoue independamment du backing store, ce qui exclut une racine probe/SMB.

L'hypothese "racine commune SMB" est **incompatible avec la topologie observee** (test_library local) et **incompatible avec les symptomes observes** (pas de hang, pas de timeout, scan termine en 12.4s). Le diagnostic pointe vers un defaut applicatif dans l'enrichissement TMDb (cause ii), pas vers une racine I/O reseau.

## Statut safety acquis (iter1+iter2)
- Item #2 dry-run: VERT, test_post_run_apply_dry_run_does_not_touch_fs PASSED, pas de fix necessaire [operationnel]
- Item #15 kill-switch path trop long: VERT, commit 06f74ad fix(safety) [FIGE]

## 1. Logs du scan

### 1.1 Sources analysees

- `docs/internal/observe/2026-06-08_ITER2_GATE1a/_scan_run.log` (3825 B, sortie console du script `scripts/_iter2_scan.py`)
- `docs/internal/observe/2026-06-08_ITER2_GATE1a/cinesort.log.tail.txt` (6364 B, tail du log applicatif `cinesort.infra.rest_server` / `cinesort.app.apply_core`)

### 1.2 Demarrage du scan [OPERATIONNEL]

**Le scan a bien demarre.** Preuves (`_scan_run.log`) :

```
L21: [iter2-scan] CineSortApi instancie. start_plan...
L22: [iter2-scan] start_plan -> ok=True run_id=20260608_215451_575 error=None
```

`run_id = 20260608_215451_575` confirme la creation effective d'un run cote backend.

A noter en amont (L1-L4) : warning Pydantic non-bloquant en mode passif :
```
[pydantic-passive] start_plan.request validation failed (flag=0, fallback dict): 1 validation error for StartPlanRequest
settings  Field required [type=missing, ...]
```
Le fallback dict a pris le relais, le run est tout de meme demarre (`ok=True`). [HYPOTHESE] La payload `_iter2_scan.py` n'enveloppe pas `library_path` dans `settings={...}` comme attendu par le schema Pydantic, mais le chemin legacy accepte la forme plate (cf. memoire `endpoints_reels`).

A noter aussi (L5-L15) : 11 messages `db: tracking schema_migrations a echoue pour vN ... : no such table: schema_migrations` au boot, idempotents (le tracker se cree ensuite). [OPERATIONNEL] non bloquant pour le scan, mais bruit a noter dans la section 5.

### 1.3 Completion du scan [OPERATIONNEL] [FIGE]

**Le scan est ALLE AU BOUT (`scan_complete = true` cote orchestrateur).** Preuves :

```
L24: [iter2-scan] idx=9/9  status=RUNNING cur='[Root 1/2] ...\test_library\RootA\Movies\t  done=False
L25: [iter2-scan] idx=6/8  status=RUNNING cur='[Root 2/2] ...\test_library\RootB\Movies\T  done=False
L26: [iter2-scan] idx=8/20 status=DONE    cur='[Root 2/2] ...\test_library\RootB\Shows\Br  done=True
L27: [iter2-scan] DONE in 12.4s  final status=DONE err=None
```

Status final = `DONE`, duree 12.4 s, `err=None`. Dashboard renvoie `ok: true`.

### 1.4 Hang ou erreur sur un fichier precis ? [OPERATIONNEL]

**Aucun hang sur un fichier specifique pendant le scan.** Les 3 echantillons de progression (L24-L26) montrent une progression normale et un passage par les 2 roots, et le status final est `DONE` en 12.4 s.

**Une seule erreur observee, mais POST-scan, dans le script d'observation lui-meme**, lors de l'impression des sample rows (`_scan_run.log` L52-L58) :

```
L52: - Traceback (most recent call last):
L53:   File "...\scripts\_iter2_scan.py", line 151, in <module>
L54:     print("  -", s)
L55:   File "...\Python312\Lib\encodings\cp1252.py", line 19, in encode
L56:     return codecs.charmap_encode(input,self.errors,encoding_table)[0]
L57:   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
L58: UnicodeEncodeError: 'charmap' codec can't encode character 'ű' in position 104: character maps to <undefined>
```

[FIGE] Cette erreur est dans l'**etage `print` du script d'observation** (encodage console cp1252 Windows incapable d'afficher `ű` = "u" hongrois). Elle n'a pas affecte le run cote backend (`status=DONE` deja emis avant). Etage : **post-scan / harness**, PAS probe ni match.

Aucun stacktrace de probe (ffprobe / mediainfo) ni de match (TMDb) dans les logs fournis.

### 1.5 Root scanne [OPERATIONNEL] [FIGE]

Les 2 roots passes par le script ont bien ete scannes :

```
L18: [iter2-scan] roots = [
       'C:\\Users\\blanc\\projects\\CineSort\\test_library\\RootA',
       'C:\\Users\\blanc\\projects\\CineSort\\test_library\\RootB'
     ]
L24: idx=9/9   cur='[Root 1/2] ...\test_library\RootA\Movies\t...'
L25: idx=6/8   cur='[Root 2/2] ...\test_library\RootB\Movies\T...'
L26: idx=8/20  cur='[Root 2/2] ...\test_library\RootB\Shows\Br...'
```

Donc bien la **bibliotheque test `test_library/RootA + RootB`** (couvre Movies + Shows).

State dir associee :
```
L17: state_dir = ...\docs\internal\observe\2026-06-08_ITER2_GATE1a\_state\CineSort
```

### 1.6 Items vus / parses / matches [OPERATIONNEL] [FIGE]

Compteurs extraits du dashboard et du `plan.jsonl` (`_scan_run.log` L30-L49) :

| Metric | Valeur | Source |
|---|---|---|
| Items vus (total_movies) | **20** | dashboard.kpis.total_movies (L36) |
| Items parses (plan.jsonl rows) | **20** | L47 `plan.jsonl rows: 20` |
| Items matches TMDb (rows with tmdb_id) | **0** | L48 `rows with tmdb_id : 0` |
| Items avec poster (rows with poster) | **0** | L49 `rows with poster : 0` |
| scored_movies | 0 | dashboard.kpis (L37) |
| score_avg / score_premium_pct | 0.0 / 0.0 | dashboard.kpis (L34-L35) |
| validated / rejected / accepted / deferred | 0 / 0 / 0 / 0 | dashboard.kpis (L39-L42) |

Echantillon row plan (L51) :
```
{'folder': '...\test_library\RootA\Movies\Big Buck Bunny (2008)',
 'title': 'Big Buck Bunny',
 'tmdb_id': None,
 'poster_url': None,
 'confidence': 'high'}
```

[FIGE] **Le parse local fonctionne (titre extrait, confidence=high), mais 0 / 20 items ont obtenu un `tmdb_id` ou un `poster_url`.** C'est le symptome central du diagnostic.

### 1.7 TMDb appele ? Reponse ? [HYPOTHESE]

**Aucune trace d'appel TMDb dans les logs fournis** (ni reussite `poster_path`, ni `401`, ni `429`, ni timeout).

Indices contextuels :
- `L16: [iter2-scan] tmdb_api_key resolved : True protection=windows_dpapi_current_user` (la cle est resolue et dechiffree via DPAPI)
- `L19: tmdb_enabled = True` (la feature est activee cote settings)
- `L20: has dpapi tmdb_api_key_secret = False` (le **chiffre brut** n'est pas present cote payload, seul le clair dechiffre l'est — coherent avec memoire `rest_api_token en CLAIR` cote IPC)
- `cinesort.log.tail.txt` couvre la fenetre 21:23:19 -> 21:24:15, soit AVANT le run `20260608_215451_575` (215451 = 21:54:51). **La queue de log applicatif fournie est anterieure au scan ITER2** et ne contient donc aucune trace TMDb du run analyse. Les seules lignes metier sont des `get_status` / `get_dashboard` / `get_sidebar_counters` et un `apply` dry_run sur un autre run `20260608_211945_637` (L39, L42-L46).

[HYPOTHESE 1] Le client TMDb n'a meme pas ete appele : court-circuit en amont (parser local renvoie `confidence=high` mais le pipeline n'invoque pas TMDb, ou alors le routage match TMDb n'est pas branche dans le mode `start_plan` utilise ici).
[HYPOTHESE 2] TMDb a ete appele mais le log applicatif tail fourni est anterieur au scan, donc les traces sont ailleurs (`cinesort.log` complet, ou rotation). A confirmer dans une section ulterieure en chargeant la fenetre 21:54:51-21:55:04.

**Statut TMDb : indetermine sur la base de ces 2 seuls fichiers, faute de log applicatif couvrant la fenetre du run.** Aucune reponse `poster_path` ni `401` observee ; le KPI `rows with poster : 0` reste le fait dur a expliquer.

### 1.8 Synthese section 1

| Question | Reponse | Marqueur |
|---|---|---|
| Scan demarre ? | Oui — `start_plan -> ok=True run_id=20260608_215451_575` (L22) | OPERATIONNEL |
| scan_complete = true ? | Oui — `final status=DONE err=None` en 12.4 s (L27) | FIGE |
| Hang sur un fichier ? | Non. Unique erreur = `UnicodeEncodeError` cp1252 dans `print()` du script harness L151, POST-scan, etage harness | FIGE |
| Root scanne ? | `test_library\RootA` + `test_library\RootB` (L18, L24-L26) | FIGE |
| Items vus / parses / matches | 20 / 20 / 0 (tmdb_id) ; 0 poster_url | FIGE |
| TMDb appele ? | Indetermine — aucune trace dans les logs fournis ; la fenetre du tail applicatif (21:23-21:24) est anterieure au run (21:54). Cle DPAPI resolue OK | HYPOTHESE |

**Constat-cle a explorer dans les sections suivantes :** parse local OK (confidence=high) mais **0 enrichissement TMDb sur 20 items**, sans aucune trace d'appel HTTP TMDb visible — soit le client n'a pas ete invoque (court-circuit pipeline), soit les logs d'appel sont hors de la fenetre tail fournie.

## 2. Erreur token "_safeBearer: token absent ou vide" (12 vues)

### 2.1 Symptome observe

Console error visible sur les 12 vues observees :
```
[dash-api] _safeBearer: token absent ou vide (token=%o) <undefined|null|"">
```

Trace emise par `web/dashboard/core/api.js` L149-L153 :
```js
function _safeBearer(token) {
  // DEBUG VERBOSE 2026-06-08 : signaler explicitement l absence de token au boot.
  if (!token) {
    try { console.error("[dash-api] _safeBearer: token absent ou vide (token=%o)", token); } catch { /* no-op */ }
    return null;
  }
  ...
}
```

Le log est emis chaque fois qu'`apiGet` / `apiPost` lit `getToken()` et obtient une valeur falsy. `getToken()` lit `sessionStorage` puis `localStorage` (`web/dashboard/core/state.js` L21).

### 2.2 Flux normal (pywebview ouvre l'app desktop) [FIGE]

Chaine d'injection du token, lue dans `app.py` L780-L842 + `web/dashboard/app.js` L113-L146 :

1. **Backend `_start_rest_server`** (`app.py` L254-L348) lit `settings.json` en `utf-8-sig` (tolere BOM PowerShell), recupere `rest_api_token` en **clair**, le passe a `RestApiServer` qui l'expose via `rest_server._token`.
2. **Construction URL** (`app.py` L819-L832) :
   ```python
   _desktop_dashboard_token = str(getattr(rest_server, "_token", "") or "")
   _desktop_dashboard_token = _desktop_dashboard_token.strip().replace("﻿", "")
   if _desktop_dashboard_token:
       _encoded_token = quote(_desktop_dashboard_token)
       main_url = f"{proto}://127.0.0.1:{port}/dashboard/?ntoken={_encoded_token}&native=1"
   ```
3. **Frontend `_detectNativeBoot`** (`web/dashboard/app.js` L113-L146) IIFE qui tourne au plus tot apres le parse :
   ```js
   const params = new URLSearchParams(window.location.search);
   const ntoken = params.get("ntoken");
   ...
   if (ntoken) {
     setToken(ntoken, true);  // persist (localStorage)
     ...
     url.searchParams.delete("ntoken");
     window.history.replaceState(...);
   }
   ```
4. **`setToken`** (`state.js` L48-L75) valide via `_URLSAFE_TOKEN_RE` puis ecrit en `sessionStorage` + `localStorage` et appelle `markTokenReady()`.

Dans ce flux, `_safeBearer` ne doit JAMAIS voir un token absent une fois `awaitToken()` resolu : `apiGet`/`apiPost` `await awaitToken()` avant `getToken()` (api.js L218-L222, L334-L344).

### 2.3 Flux observe.py (harness CDP/Playwright) [FIGE]

Lu integralement dans `scripts/observe.py` :

1. **Lancement** (L246-L252) : `subprocess.Popen(cmd, env=env, ...)` avec `cmd = dist/CineSort.exe` ou `python app.py --dev`. L'EXE/dev lance pywebview qui construit lui-meme `main_url` avec `?ntoken=...&native=1` (cf 2.2). **Aucune option de bypass : la query string ntoken est bien injectee par app.py L821, identique a un boot normal.**
2. **Connexion Playwright** (L269-L278) :
   ```python
   browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
   ctx = browser.contexts[0]
   page = ctx.pages[0]
   ```
   Playwright attache un controleur a la **page deja chargee** par pywebview avec l'URL `?ntoken=...&native=1`. Il ne re-navigue PAS.
3. **Navigation par hash** (L417-L421) :
   ```python
   page.evaluate("(h) => { window.location.hash = h.replace(/^#/,''); }", hash_target)
   page.wait_for_timeout(2500)
   ```
   On modifie uniquement le hash, pas la pathname/search -> la query `?ntoken=...` reste presente jusqu'au moment ou `_detectNativeBoot` l'a deja supprimee.
4. **Storage state preexistant** : `_make_state_dir_isolated` (L138-L146) cree un `_state` neuf et redirige `LOCALAPPDATA` (L201). C'est `settings.json` qui est isole, pas le storage Chromium/WebView2. WebView2 reutilise toujours son cache UDF utilisateur (sauf si UDF override, ce qui n'est pas fait dans observe.py).

### 2.4 Tranche cause [HYPOTHESE -> FIGE]

**Cas A (artefact harness) — REJETE**.
Si observe.py ouvrait une URL sans `ntoken`, on aurait l'erreur. Or pywebview lance par observe.py construit lui-meme l'URL via `app.py` L821 (le harness ne contourne pas cette etape). Donc le ntoken EST present dans `window.location.search` au boot.

**Cas B (bug produit reel) — RETENU avec sous-cas B.1 et B.2.**

Le log `_safeBearer: token absent ou vide` est emis dans 12 vues parce qu'il existe des chemins d'appel `apiGet`/`apiPost` qui passent malgre `awaitToken()` :

- **B.1 — Token rejete par `setToken` AVANT persistance**.
  `state.js` L48-L70 : `setToken` valide le `raw` contre `_URLSAFE_TOKEN_RE = /^[A-Za-z0-9_\-]{1,128}$/`. Si le token contient un caractere non-urlsafe (BOM U+FEFF qui aurait survecu au `strip().replace("﻿","")` de app.py L798, em-dash, percent-decoding pathologique), `setToken` **rejette silencieusement** et n'appelle PAS `markTokenReady()`. Le gate `awaitToken()` reste en attente jusqu'au deadline 2s (`state.js` `_AWAIT_TOKEN_DEADLINE_MS`) puis debloque sans token -> `getToken()` retourne `""` -> `_safeBearer("")` log l'erreur.
  Probabilite : MOYENNE. L'instrumentation `[DEBUG-NTOKEN]` de app.py (L799-L839) et le log `[state] setToken: token non-urlsafe REJETE` permettraient de confirmer mais ne sont visibles que si `CINESORT_DEBUG=1`. Observe.py n'exporte pas cette variable.

- **B.2 — Requetes API anterieures a `markTokenReady`**.
  `state.js` L96-L116 documente le bug originel `markTokenAbsent` qui debloquait IMMEDIATEMENT `awaitToken()` -> les 4 fetchs initiaux partaient sans Bearer. Le fix v1.5.0 + 2026-06-05 (`api.js` L334-L340, `app.js` L160-L168) differe le deblocage en mode natif (`_ABSENT_GRACE_NATIVE_MS`). MAIS : le code-path "log uniquement" `_safeBearer` peut toujours etre appele par des handlers/modules qui ne respectent pas le gate (ex : un module ES qui appelle `_safeBearer` directement, ou un module qui passe par un autre helper).
  Probabilite : FAIBLE. Le grep montre que `_safeBearer` n'est utilise QUE depuis `api.js` apres `await awaitToken()` (api.js L218-L222, L334-L344, L597-L603).

- **B.3 — Token effectivement vide cote backend**.
  `app.py` L840-L842 :
  ```python
  else:
      main_url = f"{proto}://127.0.0.1:{port}/dashboard/?native=1"
      print("[REST] AVERTISSEMENT : main_url SANS ntoken (rest_server._token vide)", ...)
  ```
  Si `rest_server._token == ""`, l'URL est construite SANS `?ntoken=...`. Le frontend tombe dans la branche L147-L168 de `_detectNativeBoot` ("pas de ntoken dans URL"), `markTokenAbsent({native:true})` est appele apres delai, puis `_safeBearer(null)` log.
  Probabilite : HAUTE pour observe.py specifiquement. Le harness ecrit `settings.json` (L227-L238 d'observe.py) avec :
  ```python
  seed = {
      "root": ...,
      "roots": ...,
      "state_dir": ...,
      "tmdb_enabled": False,
      "auto_check_updates": False,
      "rest_api_port": 8650,
  }
  ```
  **`rest_api_token` est absent du seed.** Au boot, `apply_settings_defaults` regenere un token aleatoire, MAIS `_start_rest_server` (app.py L308-L347) a deja un fallback : il relit `settings.json` en `utf-8-sig` et persiste le token genere via `api.settings.save_settings(...)` (L336-L340). Donc le token devrait etre present en memoire et reinjecte dans l'URL. **A confirmer par la stderr de l'EXE : presence/absence du log `[REST] main_url = ...?ntoken=...` vs `[REST] AVERTISSEMENT : main_url SANS ntoken`.**

### 2.5 Tranche finale [HYPOTHESE forte]

**Cas RETENU : MIXTE (B.3 dominant + B.1 secondaire).**

- En **lancement pywebview normal utilisateur** (settings.json deja persiste avec un token stable) : token present, `_safeBearer` ne devrait PAS logger. Si l'utilisateur voit quand meme le message en 12 vues, c'est probablement B.1 (BOM/non-ASCII glissant) -> regarder la stderr `[DEBUG-NTOKEN]` avec `CINESORT_DEBUG=1`.
- En **lancement observe.py** (settings.json seed minimal sans `rest_api_token`) : B.3 plausible si la regeneration de token n'est pas reinjectee dans `_desktop_dashboard_token` au moment de la construction de l'URL (race entre `api.settings.save_settings` et la lecture L794). **Hypothese: la regen via `apply_settings_defaults` est ecrite via `api.settings.save_settings` (L336-L338) MAIS la lecture L794 utilise `rest_server._token` deja resolu lors de `RestApiServer.start()` AVANT cette regen -> incoherence possible si `_start_rest_server` est appele AVANT que `apply_settings_defaults` ait ecrit le token.**

### 2.6 Consequence reelle [FIGE]

**Le bypass localhost dispense effectivement de l'auth Bearer.**

Preuve `cinesort/infra/rest_server.py` L433-L464 (commentaire 2026-06-08) :
```python
def _check_auth(self) -> bool:
    # 2026-06-08 — BYPASS LOCALHOST DESKTOP TRUSTED
    ...
    client_ip = self.client_address[0] if self.client_address else ""
    bypass_disabled = os.environ.get("CINESORT_DISABLE_LOCAL_AUTH", "0").strip() == "1"
    if (
        not bypass_disabled
        and client_ip in _LOCAL_CLIENT_IPS  # {"127.0.0.1","::1","::ffff:127.0.0.1"}
        and self.bind_host == "127.0.0.1"
    ):
        logger.info("Auth bypass localhost (client=%s, bind=%s) — desktop trusted mode", ...)
        return True
```

Conditions toutes remplies dans pywebview desktop + observe.py :
- `client_ip` = `127.0.0.1` (Chromium WebView2 -> serveur REST local)
- `bind_host` = `127.0.0.1` (settings par defaut)
- `CINESORT_DISABLE_LOCAL_AUTH` non set

**Donc :**
- Les appels `apiGet("/api/library/get_dashboard")`, `/api/library/get_global_stats`, etc. **passent en 200 OK meme sans header `Authorization: Bearer ...`**.
- Le chargement bibliotheque/poster TMDb cote backend **n'est PAS bloque par l'auth**.

### 2.7 Verdict [FIGE]

> Le log `_safeBearer: token absent ou vide` est un **bruit console NON CRITIQUE** dans le contexte observe.py et pywebview localhost :
> - **Cause** : token jamais injecte en sessionStorage/localStorage cote frontend (B.3 dominant : `rest_api_token` absent du seed `settings.json` du harness, ou race lecture/regen ; B.1 secondaire : token rejete pour non-urlsafe).
> - **Impact reel** : NUL sur la fonctionnalite. Le bypass localhost (`_check_auth` L433-L464) absorbe l'absence de Bearer. Les fetchs API repondent 200, le dashboard se charge, les requetes poster TMDb partent normalement.
> - **Lien avec le symptome posters** : aucun. Les 0 posters observes section 1.6 ne sont PAS causes par cette absence de Bearer (le bypass localhost les laisse passer). La cause est ailleurs (TMDb non appele, ou cle TMDb invalide — a explorer sections 3-4).

### 2.8 Recommandations diagnostiques (sans appliquer)

1. **Verifier B.3 dans observe.py** : ajouter `rest_api_token` au seed `settings_path.write_text(...)` (L227-L238) avec une chaine fixe de 32+ chars urlsafe (ex `"observe-harness-token-fixed-32chars"`) -> elimine la regen aleatoire et la race.
2. **Verifier B.1 en runtime normal** : relancer pywebview avec `CINESORT_DEBUG=1` et lire stderr -> messages `[DEBUG-NTOKEN]` + `[state] setToken: token non-urlsafe REJETE` confirmeront ou infirmeront le BOM/non-ASCII.
3. **Reduire bruit console sans masquer le bug** : downgrader le log `_safeBearer: token absent` en `console.debug` quand `window.__CINESORT_NATIVE__ === true` ET hostname `127.0.0.1` (le bypass est garanti). Garder `console.error` en mode web/LAN ou il signale un vrai 401 a venir.

Tous les marqueurs sont presents : FIGE pour les chaines code verifiees, HYPOTHESE pour les ratios de probabilite, OPERATIONNEL pour les preuves de log lues.

## 3. Violations CSP non-TMDB [OPERATIONNEL]

### 3.1 Sources analysees

Parsing des 17 fichiers `violations_csp.json` dans
`docs/internal/observe/2026-06-08_ITER2_GATE1a/<vue>/violations_csp.json`
(confirmes par les compteurs `csp_violations` du `summary.json`).

### 3.2 Inventaire complet des violations [FIGE]

**Total : 16 violations CSP**, reparties sur **4 vues** sur 17 observees.
**Toutes les violations sont strictement identiques en type** : `blockedURI="inline"` / `violatedDirective="style-src-attr"`.

| Vue (label)                       | Nb viol. | blockedURI | violatedDirective | sourceFile                                                    |
|-----------------------------------|---------:|------------|-------------------|---------------------------------------------------------------|
| `traitement_step_verification`    |        3 | `inline`   | `style-src-attr`  | `http://127.0.0.1:8650/dashboard/views/traitement.js`         |
| `traitement_step_doublons`        |        3 | `inline`   | `style-src-attr`  | `http://127.0.0.1:8650/dashboard/views/traitement.js`         |
| `bibliotheque`                    |        5 | `inline`   | `style-src-attr`  | `http://127.0.0.1:8650/dashboard/views/bibliotheque.js`       |
| `doublons`                        |        5 | `inline`   | `style-src-attr`  | `http://127.0.0.1:8650/dashboard/views/doublons.js`           |
| Autres vues (13)                  |        0 | —          | —                 | —                                                             |
| **TOTAL**                         |   **16** | —          | —                 | —                                                             |

Sequence 3 / 3 / 5 / 5 conforme a la mission.

Repartition par type de ressource :
- **100 % `style-src-attr`** (inline `style="..."` sur element HTML)
- 0 violation `script-src` / `img-src` / `font-src` / `connect-src`
- Aucune violation lie a un domaine externe (tout est `inline`, donc CSP source-keyword, pas une URL)

### 3.3 Diagnostic technique [FIGE]

`style-src-attr` controle **uniquement les attributs HTML `style="..."` inline** (pas les `<style>` blocks, pas les `element.style.X = ...` JS, qui relevent de `style-src-elem` ou ne sont pas couverts par CSP).

Pour `bibliotheque.js`, **une seule** ligne genere les 5 violations (verifie par Grep `style=[\"']` -> 1 occurrence) :

```js
// web/dashboard/views/bibliotheque.js:562
${[1,2,3,4,5].map(() => `<div class="v5-skeleton" style="height:64px;margin:8px 0;"></div>`).join("")}
```

5 skeletons -> 5 attributs `style="..."` inline -> 5 violations CSP cote browser. Meme schema pour `doublons.js` (5 skeletons) et `traitement.js` (3 skeletons sur 2 vues).

**Tous les autres `.style.X = ...` JS** (915-1865 dans `bibliotheque.js`, overlays/userSelect) n'apparaissent PAS dans le compteur, ce qui confirme que `style-src-attr` ne les attrape pas.

### 3.4 Criticite pour le rendu de la grille [FIGE]

| Critere                                                                 | Verdict |
|-------------------------------------------------------------------------|---------|
| Violation bloque-t-elle le JS de la grille (`renderGrid`, `_renderFilmCard`) ? | **NON**  — directive `style-src-attr`, pas `script-src`. |
| Violation bloque-t-elle le chargement d'images (posters TMDb) ?         | **NON**  — directive `style-src-attr`, pas `img-src`. |
| Violation bloque-t-elle la pose des cards `<article class="bibliotheque-card">` dans le DOM ? | **NON**  — `_renderFilmCard` (L397-446) genere des elements stylises **par classes CSS** (`bibliotheque-card`, `bibliotheque-card-poster-img`, etc.), aucun `style="..."` inline. |
| Effet visible cote utilisateur ?                                        | Cosmetique : les 5 lignes de loader (`v5-skeleton`) perdent leur `height:64px;margin:8px 0;` -> elles s'affichent dans le flux normal au lieu d'avoir la silhouette barre allongee, jusqu'a ce que la vraie grille remplace le squelette. |
| Effet sur la grille finale (apres remplacement du squelette) ?          | **AUCUN**  — la grille rendue par `_renderGrid()` (L500) puis `_renderFilmCard()` (L397) est uniquement structuree par classes (`bibliotheque-card-poster`, `bibliotheque-card-info`, `bibliotheque-card-title`). |
| Impact sur les `posters_rendered` (compteur a 0 dans `summary.json`) ?  | **AUCUN lien causal**  — le compteur est a 0 sur les **17 vues**, y compris les 13 qui n'ont **aucune** violation CSP. La cause des posters absents ne peut donc pas etre ces violations. |

### 3.5 Correlation avec POSTERS_ABSENTS [HYPOTHESE faible]

Les 17 vues retournent `verdict=POSTERS_ABSENTS` et `posters_expected=0`, `posters_rendered=0`, `image_requests=[]`. **Les vues SANS violation CSP (`accueil`, `qualite`, `historique`, `jellyfin`, `parametres*`, `aide`, `traitement*` sauf 2) ont exactement le meme verdict POSTERS_ABSENTS.** Donc la cause est en amont (aucun row de film n'est passe au render, cf. section 2 sur le token bearer absent), pas dans les violations CSP de `style-src-attr`.

### 3.6 Conclusion [FIGE]

> **Les 16 violations CSP NE bloquent PAS le code qui peuple la grille.** Elles concernent exclusivement la directive `style-src-attr` et touchent **uniquement** les `style="..."` inline des **squelettes (loaders) v5-skeleton** affiches AVANT le rendu de la grille reelle. Le moteur de rendu de la grille (`_renderFilmCard`) utilise des classes CSS, pas des attributs `style` inline, et les `<img class="bibliotheque-card-poster-img" src="...">` ne dependent ni de `style-src-attr` ni de `img-src` cite ici.

Severite : **cosmetique / bruit CSP** (a nettoyer pour proprete, classer comme dette technique).
Categorie causale : **HORS scope POSTERS_ABSENTS**.



## 4. Test cle TMDb au runtime [OPERATIONNEL] [FIGE]

### 4.1 Methodologie

Sonde live executee depuis la branche `loop/correction-2026-06` avec le venv du projet (`C:/Users/blanc/projects/CineSort/.venv`) le 2026-06-08. Aucun fix applique : test diagnostic seul, cache TMDb redirige vers `%TEMP%\cinesort_diag_tmdb_cache.json` pour ne pas polluer le cache utilisateur (`%LOCALAPPDATA%\CineSort\.cache\tmdb_cache.json`). La cle n'a jamais ete imprimee : on log uniquement longueur et booleens (cf section 4.5 sur le scrub).

Note importante : `TmdbClient` n'expose pas de `from_settings()` (verifie par Grep sur tout `cinesort/`). Pour reproduire fidelement le chemin runtime de l'EXE, on passe par `settings_support.extract_tmdb_key_from_settings_payload(data)` qui appelle `unprotect_secret(blob_b64, purpose=TMDB_KEY_PURPOSE)` (memoire DPAPI + memoire `settings utf-8-sig`), puis on instancie `TmdbClient(api_key=..., cache_path=...)` comme `film_support.py` L93, `library_actions_support.py` L423, `library_audit_support.py` L242, `run_flow_support.py` L207, `tmdb_support.py` L57/L148.

### 4.2 Etat du settings.json (sans valeur)

Lu depuis `C:/Users/blanc/AppData/Local/CineSort/settings.json` avec encoding `utf-8-sig` (tolerance BOM, cf memoire `cinesort_settings_utf8_bom`) :

| Champ | Valeur observee |
|---|---|
| `tmdb_enabled` | `True` |
| `tmdb_api_key` (legacy clair) | absent (chaine vide / inexistant) |
| `tmdb_api_key_secret` (blob DPAPI base64) | **present** (dict avec `scheme=windows_dpapi_current_user`, `blob_b64=...`) |
| `tmdb_api_key_protection` (raw) | `None` cote settings (la valeur effective est resolue par `extract_*_payload`) |
| `tmdb_language` | `None` (defaut `fr-FR` cote client, cf `_get_movie_detail_cached`) |

Coherent avec la memoire `rest_api_token CLAIR utf-8-sig` : seul `rest_api_token` reste en clair par design (transport IPC frontend<->backend), tandis que `tmdb_api_key` est obligatoirement chiffre via DPAPI au repos.

### 4.3 Resultat dechiffrement DPAPI

Apres appel `extract_tmdb_key_from_settings_payload(data)` :

| Champ retourne | Valeur |
|---|---|
| `protection` | `windows_dpapi_current_user` |
| `warning` | (chaine vide) |
| `key` (longueur seule) | **32 caracteres** (taille TMDb v3 attendue) |
| `key` (booleen) | `True` |

> [OPERATIONNEL] **Le dechiffrement DPAPI a reussi pour l'utilisateur courant.** Aucun warning n'a ete emis (pas de message "Cle TMDb protegee illisible pour cet utilisateur Windows: ..."). La cle clair en memoire fait bien 32 caracteres (forme standard d'une API key TMDb v3).

### 4.4 Appel TMDb `search_movie("Inception", year=2010)`

Instanciation : `TmdbClient(api_key=<32-char-cle-decrypted>, cache_path=Path(temp_dir)/"cinesort_diag_tmdb_cache.json")`.

Reponse (3 resultats `TmdbResult` dataclass) :

| Idx | `id` | `title` | `year` | `vote_count` | `poster_path` |
|----:|-----:|---------|------:|------------:|---------------|
| 0 | **27205** | `Inception` | 2010 | 39327 | `/aej3LRUga5rhgkmRP6XMFw3ejbl.jpg` |
| 1 | 64956 | `Inception: The Cobol Job` | 2010 | 314 | `/sNxqwtyHMNQwKWoFYDqcYTui5Ok.jpg` |
| 2 | 973484 | `Inception: Music from the Motion Picture` | 2010 | 3 | `/7uM4DyRVAcgagvhZoWrkrqMPbqV.jpg` |

Verification supplementaire `_get_movie_detail_cached(27205)` :

```
detail.poster_path = /aej3LRUga5rhgkmRP6XMFw3ejbl.jpg
```

Le path renvoye correspond au film canonique TMDb id 27205 (Inception 2010 de Christopher Nolan) — verifie par `vote_count=39327` coherent avec la popularite reelle du film.

> [OPERATIONNEL] **Aucun 401, aucun 429, aucun timeout, aucun `CircuitOpenError`.** Le client renvoie 3 candidats valides avec `poster_path` non-null pour les 3, et le detail enrichi retourne aussi un `poster_path` non-null. La cle EST ACCEPTEE par TMDb au runtime.

### 4.5 Scrub cle (compliance memoire `SCRUBBE cles/secrets PARTOUT`)

- La cle clair n'a JAMAIS ete imprimee dans la sortie (script log uniquement `len(key)` et `bool(key)`).
- Le bloc `except` capture toute `Exception`, scanne le message pour la cle, et la remplace par `<REDACTED_KEY>` avant `print` (precaution defensive, non declenchee ici car pas d'exception).
- Le cache TMDb produit (`%TEMP%\cinesort_diag_tmdb_cache.json`) contient les reponses mais PAS la cle (la cle est seulement passee en query string lors des requetes HTTP, jamais persistee dans le cache reponse).
- Ce document NE contient ni la cle clair, ni le blob `blob_b64` chiffre, ni un fragment quelconque ; seules les longueurs / booleens / proprietes structurelles sont citees.

### 4.6 Classification cause (v)

> [FIGE] **Cas (v) "cle TMDb invalide ou DPAPI deconne" -> ELIMINE.**
>
> Preuves cumulees :
> - DPAPI `unprotect_secret(purpose=TMDB_KEY_PURPOSE)` reussit (`warning=""`).
> - Cle clair en memoire = 32 caracteres (format TMDb v3 valide).
> - Endpoint TMDb v3 `/search/movie?query=Inception&year=2010&api_key=...` repond 200 OK avec 3 resultats.
> - `poster_path` est non-null pour les 3 candidats et pour le detail du candidat principal (id=27205).
> - Aucun symptome `CircuitOpenError`, `requests.exceptions.HTTPError`, `Timeout`, ni statut 401/403/429.
>
> La cle TMDb est **valide, dechiffrable, fonctionnelle au runtime**. La DPAPI ne deconne pas. Le client TMDb n'est pas le coupable.

### 4.7 Restriction du perimetre coupable

Combine avec la section 1.7 (aucun log d'appel TMDb dans la fenetre du tail) et la section 2.6 (bypass localhost dispense d'auth Bearer, donc le manque de token frontend ne bloque rien), le diagnostic se reduit a :

| Cas | Statut |
|---|---|
| (v) Cle TMDb invalide ou DPAPI casse | **ELIMINE en section 4** |
| (i) Pipeline scan court-circuite et n'invoque jamais `TmdbClient.search_movie` | **HYPOTHESE FORTE** (KPI `rows with tmdb_id=0` sur 20 items + zero trace HTTP TMDb dans le tail applicatif, alors que parse local renvoie `confidence=high`) |
| (ii) `tmdb_enabled` lu `False` quelque part dans le pipeline malgre `settings.json` a `True` | **HYPOTHESE FAIBLE** (a verifier en section 5 : voir si `build_cfg_from_settings` ou `run_flow_support` shadow le flag) |
| (iii) Resultat TMDb arrive mais `poster_path` n'est pas persiste dans `plan.jsonl` (champ jete au mapping) | **HYPOTHESE FAIBLE** (a verifier : extraction du `poster_path` dans la pipeline de scoring/decision) |
| (iv) Token frontend bloque les fetchs (-> dashboard vide) | **DEJA ELIMINE en section 2.6** (bypass localhost) |

### 4.8 Synthese section 4

> **La cle TMDb fonctionne. Le client TMDb fonctionne. DPAPI fonctionne. Le probleme `rows with tmdb_id : 0` ne vient PAS d'une cle invalide ni d'un dechiffrement casse.** Cause a chercher en amont (pipeline scan -> enrichissement TMDb, cf hypotheses (i) / (ii) / (iii) ci-dessus), pas dans `TmdbClient` ni dans le storage DPAPI.

## 5. Recommandations (sans appliquer)

> [HYPOTHESE] Toutes les recommandations ci-dessous sont des **propositions de diagnostic / fix** a executer dans une prochaine session. **AUCUNE n'a ete appliquee** dans le cadre de ce DIAG (memoire `AUCUN FIX SOURCE - DIAGNOSTIC SEUL`). Marqueurs sur chaque ligne pour distinguer ce qui est FIGE (constat dur) des HYPOTHESE (orientation a confirmer).

### 5.1 Cause (ii) — Pipeline scan -> TMDb (PRIORITAIRE)

**Objectif** : reveler pourquoi 20 items parses avec `confidence=high` n'aboutissent a aucun `tmdb_id` dans `plan.jsonl`.

1. **[HYPOTHESE] Reproduire avec log applicatif COMPLET sur la fenetre du run**.
   La cle est de capturer la fenetre `21:54:51 - 21:55:04` du run `20260608_215451_575`. Modifier `scripts/_iter2_scan.py` pour qu'il copie `%LOCALAPPDATA%\CineSort\cinesort.log` (ou `state_dir/logs/cinesort.log` en mode isole) DANS le dossier `observe/2026-06-08_ITER2_GATE1a/` apres `final status=DONE`. Le tail fourni couvrait `21:23:19 - 21:24:15`, soit AVANT le scan : c'est cette fenetre qui manque pour trancher entre les hypotheses (ii.a / ii.b / ii.c) ci-dessous.

2. **[HYPOTHESE] Tracer le point d'invocation TMDb dans `run_flow_support.py` / `plan_support.py`**.
   Lecture ciblee : `cinesort/ui/api/run_flow_support.py` L207 (instancie `TmdbClient`) et chercher dans `cinesort/app/plan_support.py` ou `cinesort/app/apply_core.py` les call sites `client.search_movie(...)` / `_get_movie_detail_cached(...)`. Verifier :
   - **ii.a** : la branche de routage condition `tmdb_enabled` ET `confidence in {"high","medium"}` declenche-t-elle bien l'appel ?
   - **ii.b** : le payload `start_plan` du harness (fallback dict sans `settings={...}`, cf section 1.2 warning Pydantic) n'a-t-il pas shadow le flag `tmdb_enabled=True` au passage ?
   - **ii.c** : le resultat de `search_movie` est-il bien remappe vers `row["tmdb_id"]` / `row["poster_url"]` au moment de l'ecriture `plan.jsonl` ?

3. **[HYPOTHESE] Sonde diagnostic ciblee `scripts/_iter3_pipeline_trace.py`** (a creer en session diagnostic, hors-fix).
   Instrumenter avec `logging.getLogger("cinesort.app.run_flow").setLevel(logging.DEBUG)` + `logger.addHandler(FileHandler(state_dir/"pipeline_trace.log"))` AVANT `start_plan`. Capturer toutes les lignes `TmdbClient.search_movie` / `_get_movie_detail_cached` / mapping `row -> plan.jsonl`. Si **0 ligne** apparait : court-circuit confirme (ii.a ou ii.b). Si N lignes mais 0 tmdb_id : defaut de mapping (ii.c).

4. **[OPERATIONNEL] Hypothese Pydantic StartPlanRequest**.
   La warning `[pydantic-passive] start_plan.request validation failed (flag=0, fallback dict): settings Field required` (section 1.2) est suspecte. Verifier que le fallback dict route bien vers la **meme** branche pipeline que le schema valide. Si le fallback dict tombe sur un chemin legacy qui invoque un sous-ensemble du pipeline (sans TMDb), ce serait l'explication du court-circuit. Test : ecrire un payload conforme dans `_iter2_scan.py` (`{"settings": {"library_path": ..., "roots": ..., "tmdb_enabled": true, ...}}`) et comparer.

### 5.2 Cause (iii) — Token frontend (NON BLOQUANT — bruit console)

**Objectif** : eliminer le bruit `_safeBearer: token absent ou vide` qui pollue 12 vues, SANS masquer un vrai 401 en mode web/LAN.

1. **[HYPOTHESE] Confirmer B.3 avec seed deterministe**.
   Patch `scripts/observe.py` L227-L238 pour ajouter `"rest_api_token": "observe-harness-token-fixed-32chars"` au seed. Re-executer GATE1a et observer si l'erreur disparait dans les 12 vues. Si oui : B.3 confirme. Si non : tomber sur B.1.

2. **[HYPOTHESE] Confirmer B.1 avec `CINESORT_DEBUG=1`**.
   Exporter `env["CINESORT_DEBUG"] = "1"` dans `observe.py` L213 (juste avant le Popen). Stderr capturera les logs `[DEBUG-NTOKEN]` (`app.py` L799-L839) et `[state] setToken: token non-urlsafe REJETE` (`state.js`). Si un log REJETE apparait : B.1 confirme, regarder le character offending.

3. **[HYPOTHESE] Reduire le bruit sans aveugler le bug**.
   Dans `web/dashboard/core/api.js` L149-L153, conditionner `console.error` -> `console.debug` quand `window.__CINESORT_NATIVE__ === true` ET `location.hostname === "127.0.0.1"`. Garder `console.error` en mode web/LAN ou il signale un vrai 401 a venir. Ne PAS supprimer le log : il reste utile en dev.

4. **[HYPOTHESE] Race regen token cote backend**.
   Dans `app.py` L780-L842 + `_start_rest_server` L308-L347, s'assurer que la regen via `api.settings.save_settings(...)` est **persistee dans `rest_server._token`** AVANT la lecture L794 `_desktop_dashboard_token = str(getattr(rest_server, "_token", "") or "")`. Si l'ordre est `_start_rest_server` -> regen -> save -> lecture L794, OK. Si l'ordre est `lecture L794` -> `_start_rest_server` -> regen -> save, le token sera vide a la construction d'URL.

### 5.3 Cause (iv) — Violations CSP cosmetiques (DETTE)

**Objectif** : nettoyer les 16 violations `style-src-attr` sans toucher au comportement de la grille (deja sain).

1. **[HYPOTHESE] Migrer les 3 squelettes vers classes CSS**.
   - `web/dashboard/views/bibliotheque.js:562` : remplacer `style="height:64px;margin:8px 0;"` par `class="v5-skeleton v5-skeleton-row"`.
   - Ajouter dans `web/dashboard/views/bibliotheque.css` (ou tokens partages) :
     ```css
     .v5-skeleton-row { height: 64px; margin: 8px 0; }
     ```
   - Meme pattern pour `web/dashboard/views/doublons.js` (5 occurrences) et `web/dashboard/views/traitement.js` (3 occurrences x 2 vues = 6 inline -> 1 class).
   - Risque : NUL (cosmetique, ne touche pas la grille rendue).

2. **[HYPOTHESE] Ne PAS desactiver la directive `style-src-attr`**.
   Garder le filtre actif (security hygiene) : c'est une bonne pratique contre les injections de style attribute. Le fix doit etre cote source (classes CSS), pas cote header CSP.

### 5.4 Hygiene secondaire (HORS scope POSTERS mais utile)

1. **[HYPOTHESE] Fix `UnicodeEncodeError` dans `scripts/_iter2_scan.py` L151**.
   Le `print("  -", s)` echoue sur le caractere `ű` (u-double-acute hongrois) en console cp1252. Solutions au choix :
   - Encoder explicit : `print(("  - " + str(s)).encode("utf-8", errors="replace").decode("ascii", errors="replace"))`.
   - Forcer `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` en haut du script (Python 3.7+).
   - Privilegier la 2e option, plus generique pour tous les scripts d'observation.

2. **[HYPOTHESE] Bruit `db: tracking schema_migrations a echoue pour vN ... : no such table: schema_migrations`**.
   11 messages au boot (section 1.2 L5-L15). Comportement idempotent (le tracker se cree ensuite), mais bruit log inutile. Dans `cinesort/infra/db/migration_manager.py`, transformer le `logger.warning` en `logger.debug` quand le code d'erreur SQLite est `no such table: schema_migrations` ET que la migration suivante est CREATE TABLE schema_migrations (premier boot). Garder `warning` pour les vrais echecs.

3. **[HYPOTHESE] Logger `[REST] AVERTISSEMENT : main_url SANS ntoken`**.
   Ce log (`app.py` L840-L842) doit etre un signal d'alerte fort (ERROR + diagnostic context : longueur `_token`, valeur stripped, valeur originale len/hash). Aujourd'hui il est juste `print(...)`. Ajouter une bascule vers `logger.error` + `[DEBUG-NTOKEN]` enrichi pour fast-diagnose B.3 en prod.

### 5.5 Racine commune SMB

**NON applicable** (section EN TETE racine commune SMB = NON). Aucune recommandation specifique au probe SMB dans ce diag, car la topologie observee est strictement filesystem local. Si l'utilisateur souhaite tester un scenario NAS SMB plus tard, ouvrir un DIAG separe avec un root `\\server\share\...` et des seuils de timeout calibres (`infra/db/pragma_profile.py` profil `nas_smb_slow`).

### 5.6 Ordre d'execution recommande

Si on devait sortir du DIAGNOSTIC SEUL, l'ordre optimal serait :

1. **Cause (ii)** d'abord (5.1.1 + 5.1.3) : capturer le log applicatif complet + sonde diagnostic ciblee. Sans ca, on tatonne. C'est la SEULE cause qui produit le symptome final ; tout le reste est bruit ou faux positif.
2. **Cause (iii)** ensuite (5.2.1 + 5.2.2) : test deterministe avec seed token fixe pour eliminer B.3, puis CINESORT_DEBUG=1 pour eliminer B.1. Pas urgent (impact nul), mais elimine le bruit qui distrait le diagnostic.
3. **Hygiene (5.4)** quand calme : encoding console, tracking schema_migrations, log REST en error.
4. **Cosmetique (iv)** en dette technique : migrer les 3 squelettes vers classes CSS lors d'une passe UI dediee.

Resilience interruption : ce document est ecrit au fur et a mesure (memoire `ECRITURE AU FUR ET A MESURE`). Toutes les sections 1-5 sont sauvegardees a chaque edit.
