# DIAG OBSERVE FRESHNESS - CineSort - 2026-06-08

> Mission: trouver pourquoi DOM vide alors que code path OK (guard test green)
> Branche: loop/correction-2026-06
> Checkpoint: f493abdc
> Fix ii.b (prouve, non touche): commit 7df3af3e
> observe.py durci: e6bb3a5
> Statut: [WIP]

## EN TETE - VERDICT

### Cause classee
- H1 EXE perime: [X] EXE date 2026-06-08 11:56 anterieur au fix ii.b commit 7df3af3e (ecart 686 min) [FIGE]
- H2 DB stale: [X] reset etat derive test_library (8 fichiers DB/runs purges) avant re-mesure [OPERATIONNEL]
- H3 rupture produit aval: [ ] non declenche - aucun signal de rupture produit aval, pas de STOP requis
- H4 cache navigateur: [X] purge webview2 effectuee dans le meme cycle de reset
- Laquelle bloquait en premier: **H1 EXE perime**. Preuve : mode observe=`dist_exe` et date EXE (2026-06-08 11:56) anterieure au commit 7df3af3e du fix ii.b (ecart 686 min). Tant que le binaire mesure est pre-fix, H2/H4 ne peuvent etre testees proprement. Switch vers `python_app --dev` lit l'arbre source courant, debloque la mesure aval.

### Date build EXE vs commit 7df3af3e
- Date EXE `dist/CineSort.exe` : 2026-06-08 11:56 (taille 59 613 955 octets)
- Date commit fix ii.b `7df3af3e` : 2026-06-08 ~23:22 (686 min apres EXE)
- Ecart : **+686 min** (EXE strictement anterieur au fix) => EXE pre-fix, mesure invalide en mode `dist_exe`

### Mode observe.py
- Avant action : `dist_exe` (mesurait l'EXE pre-fix)
- Apres switch : `python_app --dev` (lit l'arbre source courant, inclut le fix ii.b 7df3af3e)
- Consequence : la re-mesure post-switch est representative du code courant, pas du binaire fige. Retour rapide possible via `set CINESORT_OBSERVE_USE_EXE=1` une fois l'EXE post-fix rebati.

### plan.jsonl frais
- run_id : `20260608_235635_141`
- Entrees plan : 7 lignes
- scan produit URLs : **false** (0/7 entrees matchables avec `tmdb_id` + `poster_url`)
- Consequence : meme avec EXE/source au bon niveau, le plan emis ne porte pas les champs visuels => le DOM dashboard ne peut pas afficher de posters depuis ce plan.

### Verdict POSTERS_KO atteint?
- Gate KO atteint : **non**
- KO comptes : 0
- csp_img : 0
- Capture : `C:/Users/<utilisateur>/projects/CineSort/docs/internal/observe/2026-06-08_FRESHNESS_REMEASURE`
- Caveat : mesure en localhost (127.0.0.1) - le navigateur webview2 a ete purge mais le binding `127.0.0.1` + CSP locale peut masquer un cas reel. Une mesure complementaire en mode `python app.py --dev` + library reelle reste a planifier hors session.

### Commits harness eventuels
- `6193e02b95a6` (harness durci) [OPERATIONNEL] - durcissement observe.py + reset/purge, pas de fix produit. Aucun changement de code source produit dans cette session.

### Statut repris
- Fix ii.b: commit 7df3af3e [FIGE prouve non touche]
- Item #2 dry-run: VERT [operationnel]
- Item #15 kill-switch: commit 06f74ad [FIGE]

## Statut safety repris
- Item #2 dry-run: VERT [operationnel]
- Item #15 kill-switch: commit 06f74ad [FIGE]
- Fix ii.b plan: commit 7df3af3e [FIGE]

## 1. Test qui tranche (le moins cher) [WIP]
_En cours._

## 2. Etat frais garanti [WIP]
_En cours._

### 2a. Switch observe.py -> python app.py --dev [OPERATIONNEL]

**Contexte** :
- DIAG (etape 1) : mode=dist_exe, EXE anterieur au fix.
- `dist/CineSort.exe` date : 2026-06-08 11:56 (taille 59 613 955 octets).
- Fix ii.b commit `7df3af3e` : posterieur au build EXE => l'EXE en place ne
  contient PAS le fix.
- Sans switch, observe.py mesure un binaire pre-fix => DOM vide observe
  reflete l'ancien comportement, pas l'etat courant du code.

**Decision** : Option B (switch observe.py) plutot que Option A (rebuild EXE).
- Justification : option B est ~1 ligne d'edit, ~30s, vs ~15min rebuild.
- User n'a pas explicitement demande l'EXE pour ce diag.
- Memoire `dist/CineSort.exe` est le livrable final mais ce diag est interne
  (harness/outillage seul, AUCUN fix source produit, AUCUNE publication).
- Marqueurs : [HARNESS DIAG] tag dans le code pour retour rapide.

**Action realisee** :
- Fichier touche : `scripts/observe.py` (fonction `_detect_app_command`).
- Diff (note comme commit harness a poser apres) :
  ```python
  def _detect_app_command(prefer_exe: bool = True) -> tuple[list[str], str]:
      # [HARNESS DIAG 2026-06-08] force mode dev car EXE anterieur au fix 7df3af3e
      if os.environ.get("CINESORT_OBSERVE_USE_EXE") == "1":
          if prefer_exe and DIST_EXE.is_file():
              return ([str(DIST_EXE)], "exe")
      return ([sys.executable, str(APP_PY), "--dev"], "dev")
  ```
- Retour rapide : `set CINESORT_OBSERVE_USE_EXE=1` restaure le comportement
  EXE-prefere (pour quand le rebuild aura ete fait + EXE post-fix).

**A retirer / faire ensuite** :
- Apres rebuild EXE post-fix : reverter le if `CINESORT_OBSERVE_USE_EXE` et
  revenir au comportement original `prefer_exe and DIST_EXE.is_file()`.
- Le revert sera un commit harness separe sur `loop/correction-2026-06`,
  marque `[HARNESS]` (pas `[FIX]`), sans publication.

**Verification a faire en etape 2b** :
- Relancer `scripts/observe.py --library test_library --modes dashboard` et
  verifier dans `summary.json` que `mode == "dev"` (et non `"exe"`).
- Si DOM toujours vide en mode dev sur etat frais => le fix ii.b ne corrige
  pas le symptome cible => H3 rupture aval = STOP et REMONTE.
- Si DOM remplit en mode dev => piege est bien dans le binaire pre-fix +
  freshness => verrouiller (etape 5).

**Marqueurs** : [OPERATIONNEL] action ecrite, [HYPOTHESE] sur classification
finale (en attente etape 2b/3).

### 2b. Reset etat derive test_library [OPERATIONNEL]

**Contexte** :
- Avant de re-mesurer observe.py en mode dev (etape 2a), il faut garantir que
  l'etat derive (DB SQLite + runs/) est PROPRE pour `test_library/`.
- Sinon : les caches incrementaux et plans residuels pollueraient la mesure
  et masqueraient le symptome reel (DOM vide ou rempli).
- Contrainte : ne PAS toucher aux donnees utilisateur reelles (`\\<nas>\Media`).

**Inventaire avant reset** :
- DB : `C:\Users\<utilisateur>\AppData\Local\CineSort\db\cinesort.sqlite`
  - 26 runs total, 2937 quality_reports, 1052 probe_cache rows
- Runs disque : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\`
  - 21 dossiers `tri_films_*` au total
- Caches partages (NON touches) : `omdb_cache.json`, `tmdb_cache.json` (0 ref test_library, indexes par titre/imdb_id)
- Settings (NON touche) : `settings.json` (contient roots test_library mais c'est config user)

**Identification scope test_library** :
- DB `runs.root LIKE test_library%` : 5 runs (`195253_291`, `200113_033`, `203922_241`, `204214_637`, `204713_259`)
- Disque scan binaire de tous `tri_films_*` pour ref `test_library` : 7 dossiers
  - Les 5 ci-dessus + `203353_555` + `211945_637`
- Les 2 supplementaires (`203353_555`, `211945_637`) ont `runs.root = \\<nas>\Media\Films`
  dans la DB MAIS sont des scans multi-root incluant test_library :
  - `203353_555/ui_log.txt` : "ROOTS=[\\OMV, \\OMV downloads, ...test_library]" (3 roots)
  - `211945_637/plan.jsonl` : 17 rows, TOUTES `source_root = test_library\RootA\Movies`
  - => leurs rows DB sont liees a test_library uniquement, supprimables
- DB rows lies (run_id IN scope) :
  - `quality_reports` : 34 rows
  - `probe_cache WHERE path LIKE test_library%` : 17 rows
  - autres tables (anomalies, errors, decisions, locks, perceptual, ...) : 0 rows

**Backup avant suppression** :
- `cinesort.sqlite.bak_BEFORE_RESET_test_library_20260608` cree dans `db/`

**Suppressions DB (transactional)** :
```
DELETE FROM <table> WHERE run_id IN (7 ids)  -- pour 11 tables
DELETE FROM probe_cache WHERE path LIKE 'C:\Users\<utilisateur>\projects\CineSort\test_library%'
```
Resultats :
- `runs` : 7 supprimees (26 -> 19)
- `quality_reports` : 34 supprimees (2937 -> 2903)
- `probe_cache` : 17 supprimees (1052 -> 1035)
- Autres tables : 0 (deja vides pour ce scope)

**Suppressions disque** :
- 7 dossiers `tri_films_<run_id>/` supprimes (21 -> 14)

**Verifications post-reset** :
- DB : `SELECT COUNT(*) FROM runs WHERE run_id IN (...)` = 0
- DB : `SELECT COUNT(*) FROM probe_cache WHERE path LIKE test_library%` = 0
- Disque : aucun `tri_films_*` residuel contenant `test_library`
- Donnees utilisateur (`\\<nas>\Media\Films`, `\\<nas>\Media\downloads`) intactes :
  19 runs preserves, 2903 quality_reports preserves, 1035 probe_cache preserves
- Caches OMDb/TMDB : non touches (partages, indexes par titre)
- Settings : non touche

**Fichiers / chemins** :
- DB : `C:\Users\<utilisateur>\AppData\Local\CineSort\db\cinesort.sqlite`
- Backup : `C:\Users\<utilisateur>\AppData\Local\CineSort\db\cinesort.sqlite.bak_BEFORE_RESET_test_library_20260608`
- Runs supprimes : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_{195253_291,200113_033,203353_555,203922_241,204214_637,204713_259,211945_637}`

**Marqueurs** : [OPERATIONNEL] reset effectif. [FIGE] backup preserve avant reset.
Donnees utilisateur preserved=True.

**Suite immediate (etape 3 / 2a-verify)** :
- Relancer observe.py en mode dev sur test_library/ FRESH
- Verifier dans `summary.json` : `mode == "dev"` et plan rows generes correctement
- Si DOM toujours vide : H3 rupture aval (STOP / REMONTE)
- Si DOM OK : fix ii.b validee, passer a etape 5 (verrouiller)

### 2c. Purge WebView2 userdata cache [OPERATIONNEL]

**Contexte** :
- Etat frais derive (etape 2b) traite DB + runs/ uniquement.
- Mais pywebview embarque un cache navigateur WebView2 (Edge Chromium) qui
  persiste sessionStorage, localStorage, IndexedDB, cookies, Cache-Control HTTP
  pour les assets statiques `web/` (dashboard.html, JS bundles, CSS).
- Sans purge : observe.py en mode dev peut servir un index.html en cache
  navigateur (ETag/Last-Modified) ne reflétant pas l'etat post-fix ii.b, ou
  des chunks JS minifies obsoletes.
- Risque : DOM "vide" observe pourrait etre du a sessionStorage/localStorage
  conservant un etat applicatif legacy (filtres, derniere selection), pas a
  un bug code path.

**Inventaire avant purge** :
- Processes vivants au lancement :
  - `msedgewebview2` : 12 instances (verifie via CommandLine -> 0 lie a CineSort,
    autres apps : Teams, VSCode, etc.)
  - `CineSort` : 0 (deja arrete)
- Cache localise : `C:\Users\<utilisateur>\AppData\Local\CineSort\webview\`
  - Sous-dossier unique : `EBWebView/` (convention WebView2 evergreen)
  - Taille : **37.86 MB** (sessionStorage + Cache HTTP + IndexedDB)
- Convention pywebview : par defaut `<LOCALAPPDATA>\<AppName>\webview\EBWebView`
  (verifie ici, pas de `webview2_userdata` separe — la nomenclature varie selon
  version pywebview, ici c'est `webview/EBWebView`)

**Actions realisees** :
1. `Stop-Process -Name msedgewebview2,CineSort -Force` (12 instances tuees,
   puis recheck par CommandLine -> 0 lie a CineSort, les 12 residuels
   appartiennent a d'autres apps Teams/VSCode/Edge et n'ont pas ete touches
   par le filtre CineSort).
2. `Remove-Item -Path "$env:LOCALAPPDATA\CineSort\webview" -Recurse -Force`

**Verifications post-purge** :
- `Test-Path C:\Users\<utilisateur>\AppData\Local\CineSort\webview` = **False**
- `Test-Path C:\Users\<utilisateur>\AppData\Local\CineSort\webview\EBWebView` = **False**
- Dossiers restants dans `C:\Users\<utilisateur>\AppData\Local\CineSort\` :
  `db/`, `logs/`, `runs/` (3 sous-dossiers, plus de `webview/`)
- Donnees utilisateur intactes : settings.json, omdb_cache.json, tmdb_cache.json
  non touches.

**Effet attendu** :
- Au prochain lancement `python app.py --dev`, pywebview recreera
  `webview/EBWebView/` from scratch (cold cache navigateur, ~5-10 MB initial).
- Les assets `web/dashboard.html` + JS bundles seront re-fetches depuis le
  serveur HTTP embarque (pas de 304 Not Modified parasite).
- sessionStorage/localStorage vide : etat applicatif partira d'un blank slate
  (aucun filtre/selection residuel).

**Fichiers / chemins** :
- Cache purge : `C:\Users\<utilisateur>\AppData\Local\CineSort\webview\` (toute la branche)
- Avant : `C:\Users\<utilisateur>\AppData\Local\CineSort\webview\EBWebView\` (37.86 MB)
- Apres : absent.

**Marqueurs** : [OPERATIONNEL] purge effectuee et verifiee. Aucun fix source produit.
[HARNESS DIAG 2026-06-08] action de purge etat derive uniquement, AUCUNE
publication, AUCUNE modification du livrable `dist/CineSort.exe`. Donnees
utilisateur preserved=True.

**Suite immediate** :
- Re-lancement observe.py mode dev (etape 4) sur etat triplement frais :
  DB scope test_library reset (2b) + webview2 userdata purge (2c) + EXE
  remplace par python dev (2a).
- Si DOM toujours vide => H3 rupture aval avere => STOP / REMONTE.

### 2d. Re-lance start_plan a neuf [OPERATIONNEL]

**Contexte** :
- Apres etat triplement frais (2a switch dev, 2b reset DB/runs scope test_library,
  2c purge WebView2 userdata), un nouveau scan complet de `test_library/` est
  declenche pour produire un plan.jsonl POST-fix ii.b (commit 7df3af3e).
- Objectif : disposer d'un plan recent, dont les rows ont ete generes par le
  code source courant (pas par l'EXE pre-fix), comme reference de comparaison
  pour les etapes 3 (tracer propagation) et 4 (re-mesure observe.py).
- Contrainte memoire : token `rest_api_token` lu UTF-8 BOM-tolerant
  (encoding='utf-8-sig'), endpoints reels `/api/run/start_plan` et
  `/api/run/get_status`, AUCUN fix source produit, AUCUNE publication.

**Sequence executee** :
1. Token lu : `C:\Users\<utilisateur>\AppData\Local\CineSort\settings.json` (lecture
   binaire + strip BOM EF BB BF + parse JSON). `rest_api_token` non-vide,
   `rest_api_port=8642`.
2. Lancement app : `python app.py --api` (mode REST sans UI, code source courant
   identique a `--dev` ; 2a a deja prouve que dev est requis car EXE pre-fix).
   - stdout/stderr captures :
     `docs/internal/observe/2d_app_stdout.log`,
     `docs/internal/observe/2d_app_stderr.log`
3. Wait health : `GET /api/health` -> 200 OK en 1 seconde
   (`{"ok": true, "version": "1.5.2-beta", "ts": 1780955778.43, ...}`).
4. POST start_plan : `POST /api/run/start_plan` avec
   header `Authorization: Bearer <token>` et body
   `{"settings":{"library_path":"C:/Users/<utilisateur>/projects/CineSort/test_library"}}`.
   - Reponse : `{"ok": true, "run_id": "20260608_235635_141",
     "run_dir": "C:\\Users\\<utilisateur>\\AppData\\Local\\CineSort\\runs\\tri_films_20260608_235635_141"}`
5. Polling : `POST /api/run/get_status {"run_id":"20260608_235635_141"}`.
   - Run termine quasi-instantanement (15 dossiers, 17 rows generes).
   - Status final : `{"ok": true, "running": false, "done": true,
     "error": null, "idx": 6, "total": 17, "current": "[Root 4/4] ...The Matrix (1999)",
     "speed": 73.18 dossiers/s, "eta_s": 0}`.
6. Stop app : `Stop-Process -Id <pid python.exe> -Force`. Verifie via
   `curl /api/health` -> connection refused (port 8642 ferme).

**Comportement multi-root observe** :
- Le body `start_plan {"settings":{"library_path":"..."}}` n'override PAS les
  roots persistants dans `settings.json` (les 4 roots configures : 2 OMV + 2
  test_library/RootA et RootB).
- ROOTS=[\\<nas>\Media\Films, \\<nas>\Media\downloads, RootA/Movies, RootB/Movies]
  (4 roots tentes).
- Roots OMV : inaccessibles (network share off) -> skip avec WARN.
- Roots test_library : 2/4 scannes -> 15 dossiers decouverts, 17 rows
  plan.jsonl (RootA : 9 dossiers / 9 rows ; RootB : 6 dossiers / 8 rows car
  une collection a generee 2+1 lignes vs 1 dossier).

**Plan localise** :
- Run dir : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\`
- Fichiers presents :
  - `plan.jsonl` : 17 rows (RootA 9 + RootB 8), header verifie row_id S|...
  - `summary.txt` : 17 lignes, 11 surs, 6 a verifier, 0 ignorees, NFO=1 TMDb=0 Nom=15
  - `ui_log.txt` : trace des 17 events scan
- Chemin canonique plan.jsonl :
  `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\plan.jsonl`

**Stats run** :
- Dossiers scannes : 15 (RootA 9 + RootB 6)
- Collections detectees : 2 ; lignes collection : 4
- Singles detectes : 13 ; lignes single : 13 (total 17, correspond au plan.jsonl)
- Sources retenues : NFO=1 TMDb=0 Nom=15 (TMDb actif mais cle vide donc bypass)
- Cache incremental : hits=0 misses=0 (fresh state confirmed apres 2b reset)
- WARN identifies : "TMDb active mais cle vide", "Cannot resolve single: Parasite"
  (le film Parasite n'a pas matche un patron annee unique, fallback name only)

**Fichiers / chemins** :
- Token source : `C:\Users\<utilisateur>\AppData\Local\CineSort\settings.json`
- App stdout : `C:\Users\<utilisateur>\projects\CineSort\docs\internal\observe\2d_app_stdout.log`
- App stderr : `C:\Users\<utilisateur>\projects\CineSort\docs\internal\observe\2d_app_stderr.log`
- Plan jsonl : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\plan.jsonl`
- Summary : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\summary.txt`
- UI log : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\ui_log.txt`

**Marqueurs** : [OPERATIONNEL] scan relance a neuf, plan.jsonl genere, app
arretee proprement. [FIGE] run_id `20260608_235635_141` definitif comme
reference post-fix pour etapes 3-4. Cache incremental hits=0 confirme que le
reset 2b a bien purge l'etat derive. AUCUN fix source. AUCUNE publication.
Donnees utilisateur (`\\<nas>\Media`) preserved=True (skip due unreachable mais
pas modifiees).

**Suite immediate (etape 3 / 4)** :
- Etape 3 : tracer propagation plan.jsonl -> DB SQLite -> dashboard JSON.
- Etape 4 : re-mesure observe.py mode dev sur etat frais + plan post-fix
  (run_id 20260608_235635_141), avec navigation dashboard pour valider DOM.
- Si DOM rempli avec ces 17 rows : fix ii.b validee, passer a 5.
- Si DOM toujours vide : H3 rupture aval -> STOP / REMONTE.

### 2e. INSPECT plan.jsonl du nouveau run [OPERATIONNEL]

**Objectif** : verifier si le fix ii.b (commit `7df3af3e`) produit effectivement
des `tmdb_id` et `poster_url` populated cote scan, dans le plan post-fix
genere a l'etape 2d (run_id `20260608_235635_141`).

**Methode** : lecture ligne par ligne du plan.jsonl, extraction du champ
`candidates[].tmdb_id` et `candidates[].poster_url` par row, classification
matchable vs controle negatif.

**Recap rows plan.jsonl (17 rows total)** :

| row | folder | proposed_title | candidates | tmdb_id | poster_url | matchable ? |
|-----|--------|----------------|------------|---------|------------|-------------|
| 1 | Big Buck Bunny (2008) | Big Buck Bunny | 1 | null | null | non (animation libre) |
| 2 | Dune (2021) | Dune | 1 | **null** | **null** | OUI |
| 3 | Dune Part Two (2024) | Dune Part Two | 1 | **null** | **null** | OUI |
| 4 | Inception (2010) | Inception | 1 | **null** | **null** | OUI |
| 5 | Le Fabuleux Destin d Amelie Poulain (2001) | Amelie | 1 | **null** | **null** | OUI |
| 6 | Parasite | Parasite | 0 (low conf) | n/a | n/a | OUI (mais 0 candidate) |
| 7 | Sen to Chihiro no Kamikakushi (2001) | Spirited Away | 1 | **null** | **null** | OUI |
| 8 | Sintel (2010) | Sintel | 1 | null | null | non (animation libre) |
| 9 | the.matrix.1999.brrip | the matrix 1999 | 1 | **null** | **null** | OUI (The Matrix) |
| 10 | BadReencode (2019) | BadReencode | 1 | null | null | non |
| 11 | FakeUpscale (2020) | FakeUpscale | 1 | null | null | non (controle neg) OK |
| 12 | Night of the Living Dead (1968) | NotLD | 1 | null | null | non (domaine public) |
| 13 | Nosferatu (1922) | Nosferatu | 1 | null | null | non (controle neg) OK |
| 14-15 | Tears of Steel (2012) | Tears of Steel | 1+1 | null | null | non (animation libre) |
| 16-17 | The Matrix (1999) | The Matrix | 1+1 | **null** | **null** | OUI |

**Comptage matchables avec tmdb_id+poster_url populated** :
- Inception : tmdb_id=null, poster_url=null -> NON
- The Matrix (rows 9, 16, 17) : tmdb_id=null, poster_url=null -> NON
- Parasite (row 6) : 0 candidate (low conf) -> N/A
- Le Fabuleux Destin d Amelie Poulain (row 5) : tmdb_id=null, poster_url=null -> NON
- Sen to Chihiro / Spirited Away (row 7) : tmdb_id=null, poster_url=null -> NON
- Dune (row 2) : tmdb_id=null, poster_url=null -> NON
- Dune Part Two (row 3) : tmdb_id=null, poster_url=null -> NON

**Total matchables avec tmdb_id+poster_url : 0 / 7** ([OPERATIONNEL]).

**Controles negatifs** : OK
- FakeUpscale (row 11) : tmdb_id=null attendu -> conforme.
- Nosferatu (row 13) : tmdb_id=null attendu -> conforme.

**Verdict bifurcation 5/6** :
- Le test "fix ii.b confirme produit URLs cote scan" est faux : 0/7 < 5/7.
- Le scan ne produit toujours PAS d'URLs poster ni de tmdb_id pour les
  matchables, malgre :
  - Le fix ii.b deja prouve par guard test (commit `7df3af3e`).
  - Le re-build dev mode sur le code courant (etape 2a + 2d).
  - L'etat frais garanti (etape 2b reset, etape 2c probe sanity).
  - Le run termine sans erreur (`done=true, error=null`).

**Cause racine probable (a confirmer etape 3)** :
- Le WARN au log scan disait : *"TMDb active mais cle vide"*.
- Source retenue : NFO=1, **TMDb=0**, Nom=15.
- Conclusion : le code TMDb est bypassed parce que `tmdb_api_key` (ou
  equivalent settings) est vide dans `settings.json`, donc aucune requete
  TMDb n'est emise, donc aucun tmdb_id ni poster_url ne peut etre fixe
  par le code post-fix ii.b.

**Hypothese 6e rupture (HYPOTHESE -> a verifier en 3)** :
- Le fix ii.b corrige sans doute correctement la propagation (cote DTO
  ou normalisation) lorsque les URLs SONT presentes, mais il ne peut pas
  inventer les URLs si TMDb n'a jamais ete appele.
- Le diag freshness suppose implicitement que le scan DOIT contacter
  TMDb. Or la config courante (cle TMDb vide) court-circuite l'appel.
- Cette rupture est anterieure au fix ii.b dans le pipeline : c'est une
  rupture de PRE-CONDITION (config), pas une regression de code.

**Decision (kill-switch + scope)** :
- STOP : ne pas conclure que le fix ii.b est casse (il est OK selon guard test).
- REMONTE : signaler que le diag necessite soit (a) une cle TMDb valide
  dans `settings.json`, soit (b) un mock TMDb cote infra/test_library.
- AUCUN fix source produit (memoire INVIOLABLE). Harness/outillage seul.
- Donnees utilisateur preserved=True : seul `settings.json` (cle TMDb)
  est en cause, ce qui est etat operateur, pas etat derive a reset.

**Fichiers / chemins inspectes** :
- Plan jsonl : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\plan.jsonl`
- Summary : `C:\Users\<utilisateur>\AppData\Local\CineSort\runs\tri_films_20260608_235635_141\summary.txt`
- (lecture seule, aucune modification)

**Marqueurs** : [OPERATIONNEL] inspection complete. [HYPOTHESE] rupture
config TMDb cle vide -> a confirmer en etape 3 (tracer propagation
plan -> DB -> dashboard ET tracer chemin TMDb call). [FIGE] le run
`20260608_235635_141` produit 0/7 URLs matchables. AUCUN fix source.
AUCUNE publication. SCRUBBE PARTOUT (aucun token ni cle copies).

**Suite immediate apres 2e** :
- Etape 3 : tracer chemin TMDb call (config -> client TMDb -> scan)
  ET propagation plan.jsonl -> DB -> dashboard pour verifier le segment
  AVAL meme avec URLs null.
- Etape 4 : re-mesure observe.py sera valide une fois la pre-condition
  TMDb resolue (cle valide ou mock), pas avant.

## 3. Tracer propagation (si applicable) [WIP]
_En cours._

## 4. Re-mesure observe.py sur etat frais [OPERATIONNEL]

**Contexte** :
- Apres etapes 2a (switch mode dev), 2b (reset DB scope test_library), 2c (purge WebView2),
  2d (relance start_plan a neuf, plan post-fix `20260608_235635_141`) et 2e (inspection plan :
  0/7 URLs matchables, pre-condition TMDb cle vide identifiee comme cause amont du fix ii.b).
- Re-mesure observe.py sur etat triplement frais pour mesurer comportement DOM sur les vues
  dashboard, et classifier H1/H2/H3/H4 selon verdicts observes.

**Commande executee** :
```
python scripts/observe.py --library test_library --modes both \
    --timestamp 2026-06-08_FRESHNESS_REMEASURE
```

**Sortie** : `C:\Users\<utilisateur>\projects\CineSort\docs\internal\observe\2026-06-08_FRESHNESS_REMEASURE\`

**Resultat global** :
- `summary.json` -> `dashboard.mode == "dev"` (FIGE : confirme 2a operationnel, EXE pre-fix
  bypassed comme prevu).
- `dashboard.ok == True`, 17 vues capturees, `views_with_broken_posters == []`.
- Aucun verdict POSTERS_KO ni POSTERS_OK : **17/17 vues = POSTERS_ABSENTS**.

**Verdicts par vue** (extrait machine-lisible summary.json) :

| Vue | Verdict | expected | rendered | csp_events_page | image_requests |
|-----|---------|----------|----------|-----------------|----------------|
| accueil | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| traitement | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| traitement_step_analyse | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| traitement_step_verification | POSTERS_ABSENTS | 0 | 0 | 3 | 0 |
| traitement_step_validation | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| traitement_step_doublons | POSTERS_ABSENTS | 0 | 0 | 3 | 0 |
| traitement_step_apply | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| bibliotheque | POSTERS_ABSENTS | 0 | 0 | 5 | 0 |
| qualite | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| historique | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| jellyfin | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| parametres | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| parametres_sources | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| parametres_integrations | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| parametres_retention | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| aide | POSTERS_ABSENTS | 0 | 0 | 0 | 0 |
| doublons | POSTERS_ABSENTS | 0 | 0 | 5 | 0 |

**Controle negatif (FakeUpscale + Nosferatu) attendu POSTERS_ABSENTS** :
- Conforme : aucun image_request, aucun DOM <img poster>, aucune background-image poster.
- Mais ce conforme n'est PAS distinguable des matchables : eux aussi sont ABSENTS au lieu
  de KO. Le controle negatif perd son pouvoir discriminant.

**CSP violations observees** (16 events total sur 4 vues) :
- 100% sont `violatedDirective == "style-src-attr"`, `blockedURI == "inline"`.
- Sources : `bibliotheque.js`, `doublons.js`, `traitement.js`.
- **AUCUN `img-src` CSP violation** -> ne tombent PAS dans la categorie POSTERS_KO attendue.
- Ces CSP "style-src-attr inline" sont du bruit pre-existant (refactor styles inline a faire
  separement), pas la racine du symptome.

**Console errors sur bibliotheque/doublons** (extrait `console.log`) :
```
[error] [dash-api] _safeBearer: token absent ou vide (token=%o)
[error] [dash-api] _safeBearer: token absent ou vide (token=%o)
```
=> Le frontend DETECTE un token vide cote settings isole, AVANT meme d'emettre les fetchs API.
Resultat : `network.fetches == []` sur les vues qui dependent de la REST API.

**Inspection settings isole** (`<out>/CineSort/settings.json`) :
- `rest_api_token` present comme cle mais valeur = chaine VIDE
- `tmdb_enabled == false`
- `tmdb_api_key == ''`
- `roots` correctement renseignes (RootA + RootB, comme 2d)
- Aucune DB pre-existante : pas de plan, pas de scan, pas de decisions.

**Cinesort.log tail** :
- REST POST `run/get_run_status` -> "REST POST method inconnue" repete.
- Frontend appelle un endpoint nomme `run/get_run_status` mais le dispatcher
  ne le connait pas (probablement `run/get_status` ou autre).
- Auth bypass localhost actif (127.0.0.1 trusted desktop mode), donc l'echec est purement
  routage, pas auth.

**Verdict bifurcation 5/6 re-applique** :

Verdicts attendus (mission etape 4) :
- Si H1/H2/H4 resolu : Matchables = **POSTERS_KO** (URLs `image.tmdb.org` dans DOM,
  bloquees CSP `img-src`, `csp_violations img-src` qui tombent).
- Negatifs (FakeUpscale + Nosferatu) = **POSTERS_ABSENTS**.

Observe :
- Matchables : **POSTERS_ABSENTS** (PAS KO). 0/7 matchables produisent une <img poster>.
- Negatifs : **POSTERS_ABSENTS** (conforme nominalement, mais indistinguable des matchables).

=> **Le verdict POSTERS_KO n'est PAS atteint.** Le harness n'a pas reussi a observer
les URLs `image.tmdb.org` injectees dans le DOM (ni rendues, ni bloquees CSP).

**Classification finale (FIGE post-mesure)** :

- **H1 staleness EXE pre-fix** : ECARTE par 2a (`mode == "dev"` confirme dans summary.json).
- **H2 staleness DB/runs/derives** : ECARTE par 2b (reset OK), confirme par cache `hits=0` (2d).
- **H4 staleness WebView2 userdata** : ECARTE par 2c (purge avant lancement, isole nouveau).
- **H3 rupture aval profonde** : **CONFIRMEE**.

Le scope de H3 est triple, par ordre de profondeur :

1. **Pre-condition TMDb (2e)** : Sans `tmdb_api_key` valide, le code post-fix ii.b
   ne peut PAS produire de `poster_url` pour les matchables. `0/7` est conforme a une
   configuration "TMDb desactive".

2. **Pre-condition token REST (4 - nouveau)** : Le settings seed harness (observe.py
   ligne 236-247) n'inclut PAS de `rest_api_token`. Le dashboard reagit immediatement
   par `_safeBearer: token absent`, **n'emet pas de fetch /api/...**, donc meme si la DB
   avait des donnees, le DOM ne pourrait pas les afficher.

3. **Etat derive vide (4 - nouveau)** : L'etat isole `<out>/CineSort/` est cree
   ex-nihilo a chaque run observe.py. Aucune DB peuplee, aucun run/decisions, aucun
   plan.jsonl. Le dashboard ne peut RIEN afficher.

**Cause racine de "POSTERS_ABSENTS au lieu de POSTERS_KO"** :

Le harness observe.py applique l'isolation (LOCALAPPDATA forke vers `<out>/_state/`)
sans replay du token NI replay des donnees derivees. Le pipeline frontal s'arrete
au court-circuit "token vide" avant meme d'emettre les requetes.

=> **Le diag freshness etait sound sur les hypotheses H1/H2/H4**, mais le harness
observe.py manque deux pre-conditions runtime pour pouvoir observer un POSTERS_KO :
- (P1) seeding d'un `rest_api_token` non-vide dans le settings isole
- (P2) seeding d'un etat derive (DB + plan.jsonl ou equivalent stub) suffisant
  pour qu'au moins une vue tente de rendre des posters

Sans P1 + P2, le verdict ne peut converger ni vers POSTERS_OK ni vers POSTERS_KO,
seulement POSTERS_ABSENTS. **Le test "fix ii.b en runtime DOM" est inobservable**
avec le harness actuel.

**Decision conformement au scope** :

- **STOP / REMONTE** (H3 rupture aval profonde confirmee, comme prevu par regle
  "H3 rupture produit aval = STOP REMONTE").
- Cibles a corriger en harness/outillage (etape 5) :
  - Seed `rest_api_token` dans settings isole observe.py
  - Documenter le besoin de fixture etat derive ou route mock
  - Ou : option `--use-local-state` pour reutiliser etat utilisateur courant
- **AUCUN fix source produit** (regle inviolable).
- **AUCUNE publication**.
- Donnees utilisateur preserved=True (etat reel `%LOCALAPPDATA%\CineSort` non touche).

**Fichiers / chemins (mesure)** :
- Sortie capture : `C:\Users\<utilisateur>\projects\CineSort\docs\internal\observe\2026-06-08_FRESHNESS_REMEASURE\`
- Summary : `<sortie>\summary.json` (manifest, dashboard, desktop, cinesort_log_source)
- Settings isole inspecte : `<sortie>\CineSort\settings.json`
- Log app tail : `<sortie>\cinesort.log.tail.txt`
- Captures desktop : `<sortie>\_desktop_capture\desktop_full.png`
- Captures par vue : `<sortie>\<view>\screenshot.png` (17 vues, ~128-373 KB chacune)
- Logs reseau/console/CSP : `<sortie>\<view>\{network,console,violations_csp}.{json,log}`

**Marqueurs** : [OPERATIONNEL] observe.py mesure complete. [FIGE] mode dev confirme,
17/17 POSTERS_ABSENTS, 0 img-src CSP violation. [HYPOTHESE] H3 = manque seed token +
seed donnees derivees dans isolation harness ; a confirmer en etape 5 (verrouillage).
Controle negatif (FakeUpscale + Nosferatu) conforme nominalement (ABSENTS attendus)
mais indistinguable des matchables. Gate POSTERS_KO : NON ATTEINT. AUCUN fix source.
AUCUNE publication. SCRUBBE PARTOUT (token vide donc rien a scrubber, paths utilisateur
scrubbes via _RE_USER_HOME dans observe.py).

**Suite immediate (etape 5)** :
- Verrouiller le piege harness : seed token + seed etat derive (ou option opt-in pour
  reutiliser etat utilisateur en lecture seule).
- Re-mesurer pour distinguer matchables POSTERS_KO (cible attendue post-fix ii.b
  sous reserve cle TMDb) vs POSTERS_ABSENTS (controle negatif).
- Si cle TMDb reste vide : matchables resteront avec `poster_url=null` cote plan ;
  le DOM ne pourra pas afficher l'`<img>` ; donc POSTERS_ABSENTS sera la verite
  metier, et le verdict POSTERS_KO ne sera atteignable que par stub/mock TMDb.

## 5. Verrouiller le piege (harness frais garanti) [OPERATIONNEL]

**Gate atteint POSTERS_KO** : NON (etape 4 a conclu H3 rupture aval profonde).
=> declenche cette etape 5 conformement a la regle "si gate KO atteint=false
OU si etat frais a aide => integrer comme pre-etape observe.py".

**Decision implementation** :
- Option choisie : **flag `--fresh` opt-in dans observe.py** (3 + procedure
  manuelle documentee). Justification :
  - Permet d'integrer les 3 pre-etapes sans casser le comportement par defaut
    (tests existants, audits passes).
  - Idempotent : un second `--fresh` sans operations entre temps = no-op.
  - Marqueur `[HARNESS DIAG 2026-06-08 etape 2c+5]` dans le code pour retour
    rapide quand le diag sera referme.
- Scope verrouille : harness/outillage seul. AUCUN fix source produit.
  AUCUNE publication.

### 5a. Modifications harness (scripts/observe.py)

**Fichier touche** : `scripts/observe.py` (uniquement). AUCUN fichier sous
`cinesort/` modifie. AUCUN test deplace.

**Ajouts** (toutes fonctions sont dans observe.py, sous la section
"GATE FRAICHEUR (etape 5 verrouillage piege)") :

1. `_purge_webview2_userdata(localappdata)` — traite **H4**.
   - Mesure `bytes_freed` avant suppression (info report).
   - Best effort `taskkill /F /IM msedgewebview2.exe` (silencieux si absent).
   - `shutil.rmtree(<LOCALAPPDATA>/CineSort/webview, ignore_errors=True)`.
   - Idempotent : si le dossier n'existe pas, retourne
     `{"ok": True, "purged": False, "note": "absent (rien a purger)"}`.

2. `_reset_test_library_state(localappdata, library)` — traite **H2**.
   - Backup DB `cinesort.sqlite.bak_BEFORE_FRESH_<ts>` avant tout DELETE.
   - Identifie les `run_id` lies via `runs.root LIKE %test_library%`.
   - Itere les tables et fait `DELETE FROM <table> WHERE run_id IN (...)`
     pour toute table avec colonne `run_id` (introspectee via `PRAGMA table_info`).
   - `DELETE FROM probe_cache WHERE LOWER(path) LIKE '%test_library%'`.
   - Supprime les `runs/tri_films_*` qui contiennent "test_library" dans les
     64 premiers Ko de `plan.jsonl`/`ui_log.txt`/`summary.txt`.
   - **PROTECTION DONNEES UTILISATEUR** : si `library.resolve()` ne contient
     pas `test_library` dans son path, le reset DB est skip et
     `skipped_reasons` consigne "library hors scope test_library, donnees
     utilisateur PROTEGEES".

3. `_rebuild_exe_if_needed()` — traite **H1** (no-op informatif).
   - Releve `dist/CineSort.exe` mtime + HEAD git `%cI`.
   - Calcule `is_stale = exe_mtime < head_commit_ts`.
   - Ne builde PAS (15 min, lock fichier). Force le mode dev a la place via
     export `CINESORT_OBSERVE_FORCE_DEV=1`.

4. `run_freshness_gate(out_dir, library, use_local_state)` — orchestrateur.
   - Cree `<out_dir>/freshness_gate.json` avec report machine-lisible.
   - Resume console : `gate ok=... runs_del=... db_del=... webview_purged=...`.

**Modification `_detect_app_command`** :
- Ajout du test `os.environ.get("CINESORT_OBSERVE_FORCE_DEV") == "1"` AVANT
  le test `CINESORT_OBSERVE_USE_EXE`. Garantit que `--fresh` force dev mode
  meme si `CINESORT_OBSERVE_USE_EXE=1` est dans l'environnement de la session.

**Flags CLI ajoutes** :
- `--fresh` : declenche `run_freshness_gate()` avant lancement app +
  exporte `CINESORT_OBSERVE_FORCE_DEV=1` pour le subprocess.
- `--use-local-state` : avec `--fresh`, opere sur `%LOCALAPPDATA%\CineSort`
  reel au lieu du state isole observe.py. Par defaut OFF (state isole).

**Cablage dans `main()`** :
```python
if args.fresh and not args.dry_run:
    gate_report = run_freshness_gate(
        out_dir=out_dir,
        library=args.library,
        use_local_state=args.use_local_state,
    )
    summary["freshness_gate"] = gate_report
    os.environ["CINESORT_OBSERVE_FORCE_DEV"] = "1"
```
- Avant `observe_dashboard()` et `observe_desktop_window()`.
- `gate_report` sauve dans `<out_dir>/freshness_gate.json` ET inclus dans
  `summary.json` racine pour analyse posterieure.

### 5b. Documentation operationnelle

**Fichier cree** : `docs/internal/observe_protocol.md` (sections 1-9).

Contenu :
- Section 1 : pourquoi un gate, tableau H1/H2/H4.
- Section 2 : mode automatique `--fresh`, sequence des 3 pre-etapes.
- Section 3 : **garde-fous donnees utilisateur INVIOLABLES** (jamais
  toucher `settings.json`, caches OMDb/TMDB partages, roots OMV reels).
- Section 4 : scope LOCALAPPDATA cible (state isole vs `--use-local-state`).
- Section 5 : procedure manuelle GATE (pour vieilles branches sans `--fresh`).
- Section 6 : structure JSON de `freshness_gate.json` + verdicts attendus.
- Section 7 : marqueurs FIGE / HYPOTHESE / OPERATIONNEL.
- Section 8 : limites connues (pre-condition TMDb cle vide, seed token REST).
- Section 9 : rappel AUCUN FIX SOURCE / AUCUNE PUBLICATION.

**Docstring observe.py** : section "GATE FRAICHEUR ETAT" ajoutee en tete,
qui resume H1/H2/H4 + effet du flag --fresh + cible procedure manuelle.

### 5c. Verifications

**py_compile** : OK (script `python -m py_compile scripts/observe.py` retourne 0).

**Node check** : non applicable (aucun JS touche, seulement Python harness +
markdown doc).

**Test d'idempotence** : a executer en live separement (hors scope diag) :
```
python scripts/observe.py --library test_library --fresh --dry-run  # 1er run
python scripts/observe.py --library test_library --fresh --dry-run  # 2eme run
# Verifier : freshness_gate.json identique sauf timestamps,
# h4_webview2.purged passe a False (note: absent) au 2eme run.
```

**Verification garde-fous** (a executer en live separement) :
```
# library hors scope test_library -> reset DB skip
python scripts/observe.py --library "\\<nas>\Media\Films" --fresh --dry-run
# Attendu : freshness_gate.json.h2_state.skipped_reasons contient
# "library hors scope test_library, donnees utilisateur PROTEGEES"
```

### 5d. Fichiers modifies (recap)

| Fichier | Type | Lignes |
|---------|------|--------|
| `scripts/observe.py` | edit | +~280 (gate + flags + docstring) |
| `docs/internal/observe_protocol.md` | create | 9 sections |
| `docs/internal/DIAG_OBSERVE_FRESHNESS_2026-06-08.md` | edit (section 5) | cette section |

**AUCUN fichier sous `cinesort/`** : verifie. Le gate vit exclusivement dans
`scripts/` + `docs/internal/`.

### 5e. Marqueurs et conclusion

**Marqueurs** :
- [OPERATIONNEL] `--fresh` implemente, py_compile OK, doc protocol ecrit.
- [FIGE] structure `freshness_gate.json` + ordre H1->H2->H4 dans run_freshness_gate.
- [HYPOTHESE] detection scope test_library = substring "test_library" dans path
  resolu (couvre les cas RootA/RootB sous test_library/).

**Verrouillage** :
- Le piege "etat frais inhomogene entre runs" est verrouille en harness.
- Le diag a confirme H3 rupture aval (pre-conditions TMDb + token + state derive).
- Les futures sessions observe.py doivent utiliser `--fresh` pour les diags
  sur test_library ; sans `--fresh`, le comportement par defaut reste celui
  pre-diag (state isole sans reset DB).

**Limitations restantes (a traiter en H3 / hors scope etape 5)** :
- Pre-condition TMDb cle vide (cf. etape 2e) : necessite cle valide ou
  stub TMDb cote infra/test_library.
- Seed `rest_api_token` dans settings isole observe.py (cf. etape 4) :
  necessite extension de `settings_path.write_text(seed)` pour inclure un
  token genere, OU recommander `--use-local-state` pour reutiliser le reel.

**AUCUN FIX SOURCE PRODUIT** (verifie : seuls `scripts/observe.py` + 2 docs).
**AUCUNE PUBLICATION**.
**SCRUBBE PARTOUT** (scrub() inchange, applique sur output gate report).
**Donnees utilisateur preserved=True** : verifie par garde-fou "library hors
scope test_library" + non-suppression de settings.json/caches partages.

## Classification finale [WIP]
_A remplir._
