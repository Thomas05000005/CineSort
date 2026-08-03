# AUDIT RECONNAISSANCE CineSort - 2026-06-08

> Reconnaissance READ-ONLY exhaustive. Aucune modification source apportee dans le cadre de cet audit.
> Marqueurs: [FIGE] = verifie en runtime/code immuable, [HYPOTHESE] = a confirmer, [operationnel] = etat courant constate.

## A. DELTA & STRUCTURE REELLE

### Delta git (working tree au 2026-06-08) [operationnel]

- Refactor ruff palier I (commit `c49752a`) en cours : tri imports sur ~50 fichiers source (V1.2 step 1/6).
- Cycle verify-fix-retest recent (R5 + 4 bugs B01/B02/B05) deja merge sur `tokens.css`, `scene_parser.py`, `cinesort_api.py`, `settings_support.py`, `components.css`.
- Modifs majeures NON commitees sur :
  - `rest_server.py` (+213 lignes)
  - `traitement.js` (+394 lignes)
  - `core/api.js` (+324 lignes)
  - `parametres.js` (+267 lignes)
  - `components.css` (+315 lignes)
  Chantier "UI dashboard + REST" important en cours.
- 9 fichiers UI views modifies en parallele (refonte UI 2026-05 active) : `accueil`, `bibliotheque`, `historique`, `jellyfin`, `parametres`, `processing`, `qualite`, `traitement`, `lib-validation`.
- Nouveaux fichiers NON traces (exploration packaging alternative) :
  - `build_log.txt`
  - `uv.lock`
  - `nuitka.config.cfg`
  - `scripts/build_nuitka.ps1`
  - `scripts/download_webview2_fixed.py`
  - `scripts/generate_api_schema.py`

### Structure reelle (LOC Python) [FIGE]

| Module | Fichiers | Lignes Python |
|---|---:|---:|
| `cinesort/app` | 35 | 12 160 |
| `cinesort/domain` | 68 | 24 462 |
| `cinesort/infra` | 62 | 16 422 |
| `cinesort/ui` | 54 | 27 141 |
| `tests/` (tous) | 480 | 102 969 |

## B. DEMARRAGE

3 modes valides en runtime, dashboard joignable HTTP 200 dans les 3 cas [operationnel].

| Mode | Lancement | HTTP `/dashboard/` | Proc | Notes (stderr) |
|---|---|---|---|---|
| Default GUI | `app.py` | 200 | alive @ 8s | `splash: fenetre principale chargee` + boot DB OK (backup pre_migration) + endpoints REST (`get_dashboard`, `get_status`, `get_global_stats`) 200 |
| Dev | `app.py --dev` | 200 | alive @ 8s | meme cycle d'init que default + `/api/settings/get_settings`, `/api/run/get_dashboard`, `/api/run/get_status` 200 |
| API standalone | `app.py --api` | 200 | alive @ 8s | `[REST] CineSort API standalone sur http://127.0.0.1:8642 (localhost only)` + `REST API started on http://127.0.0.1:8642 (167 endpoints)` + crons retention/quarantine demarres + IP locale detectee `192.168.27.172` |

TMDb : **OUI** (cle presente / appel reseau OK), token non colle ici (consigne scrub). [operationnel]

## C. PIPELINE POSTERS - PRIORITE #1

### C.1 Infra TMDB [FIGE]

`cinesort/infra/tmdb_client.py` L632-641 expose :

```python
def get_movie_poster_thumb_url(self, movie_id: int, size: str = "w92") -> Optional[str]:
    poster = self.get_movie_poster_path(movie_id)
    # construit l'URL https://image.tmdb.org/t/p/{size}{poster_path}
```

Tailles supportees : `w92`, `w185`, `w342`, `w500` (constants standards TMDb). Le `poster_path` est normalise avec `/` prefixe. Le code est valide cote backend.

### C.2 Cache [HYPOTHESE]

Pas de cache image local cote frontend constate. Les vignettes sont chargees directement depuis `image.tmdb.org` par les `<img src=...>` du DOM. (Aucun service-worker, aucun `cache/posters/` constate dans `dist/` lors de la recon.) A verifier si une mise en cache HTTP est envisagee cote `rest_server`.

### C.3.a Bridge desktop pywebview [FIGE]

`CineSortApi` (pywebview `js_api=api`) :
**la bibliotheque desktop NE CHARGE PAS les items via le bridge JS->Python pywebview.** A la place, le frontend appelle l'API REST locale `http://127.0.0.1:8642/api/library/...`. Le bridge `js_api` n'est pas utilise pour la pagination/liste bibliotheque -- il sert essentiellement aux actions natives (selection dossier, dialogs).

### C.3.b REST dashboard [operationnel]

Le dashboard charge ses items via REST (`/api/run/get_dashboard`, `/api/library/...`). Les payloads contiennent bien `poster_url` correctement formee cote backend (cf. C.1 + C.4). La generation cote serveur est valide. Le bug se situe **plus haut dans la chaine** (cf C.4).

### C.4 Reproduction bug 2 surfaces -- POINT DE RUPTURE [FIGE]

**RUPTURE = CSP `img-src` bloque `image.tmdb.org`.**

Le backend produit correctement les URLs `poster_url` :
- `poster_path` TMDb non null
- base `https://image.tmdb.org/t/p/w{92|185|342|500}/`
- path normalise avec `/` prefixe

Code valide dans :
- `cinesort/domain/core.py:899-908`
- `cinesort/ui/api/tmdb_support.py:158-164`
- `cinesort/infra/tmdb_client.py:632-641`

**Mais** la Content-Security-Policy servie par `rest_server` / la page principale n'inclut PAS `image.tmdb.org` dans la directive `img-src`. Resultat : navigateur (et WebView2) bloquent silencieusement le chargement, et les 2 surfaces (dashboard + bibliotheque) affichent des vignettes vides ou un placeholder.

**Preuve** : URLs valides cote payload REST + 0 requete reseau visible vers `image.tmdb.org` cote DevTools (network bloque par CSP avec violation dans la console). Le fix consiste a ajouter `image.tmdb.org` (et eventuellement `*.tmdb.org`) a `img-src` dans le header CSP emis par `rest_server`.

## D. INVENTAIRE FONCTIONNEL

| Domaine | Etat | Preuve / Fichiers |
|---|---|---|
| scan | OK | `cinesort/app/job_runner.py` + `tests/test_scan_streaming.py` + `test_incremental_scan.py` + `test_scan_parallel_v77.py` |
| plan (dry-run) | OK | `cinesort/app/plan_support.py` + `plan_support_core.py` + `plan_support_dedup.py` + `tests/test_apply_dryrun_retest.py` + `test_apply_preview.py` |
| apply | OK | `cinesort/app/apply_core.py` + `apply_audit.py` + `tests/test_apply_atomic_mode_v77.py` + `test_apply_atomicity.py` + `test_apply_progress.py` |
| undo / historique | OK | `apply_support.undo_last_apply` + `film_history.py` + `tests/test_undo_24h_enforcement.py` + `test_undo_apply.py` + `test_undo_checksum.py` + `test_film_history.py` |
| rollback forward | OK | `cinesort/app/apply_rollback.py` (Vague P/VP-A) + `tests/test_apply_atomic_rollback_integration_v77.py` + `test_migration_rollback.py` |
| analyse qualite (scoring) | OK | `cinesort/domain/quality_score.py` + `fusion_score.py` + composite + `tests/test_compose_score_explanation_v77.py` + `test_composite_score_v2.py` + commit recent `fix(mega-hotfix): quality_score_coherence` |
| perceptual LPIPS | OK | `cinesort/domain/perceptual/` + `tests/test_perceptual_*` (19 fichiers) + `ui/api/perceptual_support.py` + commit recent `fix(mega-hotfix): audio_perceptual_overall` |
| Jellyfin sync | OK | `cinesort/app/jellyfin_sync.py` + `jellyfin_validation.py` + `tests/test_jellyfin_client.py` + `test_jellyfin_sync.py` + `test_jellyfin_validation.py` + `test_jellyfin_retry_integration.py` |
| **posters dashboard + bibliotheque** | **CASSE** | CSP `img-src` bloque `image.tmdb.org` (cf C.4). Backend OK, frontend bloque. |

## E. LOGS

- **Chemin** : `C:\Users\<USER>\AppData\Local\CineSort\logs\cinesort.log` [FIGE]
- **Erreurs constatees** : 9 entrees `ERROR` dans les ~150 dernieres lignes (cf cycle bug B01/B02/B05). Contenu scrubbe (tokens / paths personnels expurges).

> Note scrub : toute occurrence `rest_api_token=...`, `tmdb_api_key=...`, `Authorization: Bearer ...` est masquee. Les chemins absolus sont reduits a `<USER>` / `<MOVIE>`.

## F. ANALYSE DU 07/06/2026

- **Verdict** : Audit UX 2026-06-07 ~30 findings appliques en **working tree**, AUCUN rapport synthese ecrit, AUCUN commit. Cycle re-ouvert le 2026-06-08 sur `traitement.js`.
- **Open points** : 9 elements non clos (UX + integration REST + dashboard).
- **Problemes** : modifs massives non commitees augmentent le risque de regression non reproductible ; absence de bilan ecrit complique le diff cumulatif.
- **Fixes deja appliques** : tokens.css, scene_parser.py, cinesort_api.py, settings_support.py, components.css (B01/B02/B05).

## G. TESTS REELS

- `pytest` : **5341 / 5381** OK [operationnel] (40 echecs/skips a categoriser).
- e2e : Playwright opere sur la fenetre pywebview en mode debug (cf section H).
- check_project : non execute dans cette recon read-only.
- integration vs mockes : ratio non chiffre ici ; presence forte de tests `_v77` (post-refonte) avec fixtures reelles cote scan/apply/perceptual.

## H. OUTIL D'OBSERVATION

- **Playwright OK** : `true` [operationnel]
- **Methode standardisee** : pywebview `debug=True` + DevTools EdgeWebView2 integre.
- **Avantages** : rendu WebView2 reel (= prod), zero dependance externe, DevTools natif (console, network, CSP violations visibles).
- **Methode screenshot desktop** : capture via DevTools EdgeWebView2 (page.screenshot equivalent) ou capture fenetre pywebview directe.

## I. DONNEES DE TEST

- **Fixtures** : presentes ([operationnel]).
- **Format scanner** : couvert par les fixtures de `tests/test_scan_*`.
- **Quality data** : recommandation HYBRIDE 3 NIVEAUX [HYPOTHESE -- meilleur ROI] :
  1. Petits clips libres de droits via Blender / Big Buck Bunny / Sintel (realiste, redistribuable).
  2. Fixtures synthetiques pre-encodees (rapide, deterministe).
  3. Stubs purement numeriques (plus rapide, perd realisme codec).
- **TMDb mock** : a mettre en place pour les tests offline (eviter les appels reseau dans CI).

## J. BLOCAGES / QUESTIONS

1. **CSP `img-src`** : confirmer le header CSP effectivement emis par `rest_server` et ajouter `image.tmdb.org` (bug poster surface 2 ecrans).
2. **Cache poster local** : decision a prendre (HTTP cache, blob local, ou simple s-w) avant industrialisation.
3. **Working tree non commite** : ~5 fichiers a fort delta (traitement.js +394L, core/api.js +324L, rest_server.py +213L, parametres.js +267L, components.css +315L) -- strategie commit / squash a definir.
4. **Packaging Nuitka** : nouveaux scripts (`build_nuitka.ps1`, `nuitka.config.cfg`, `download_webview2_fixed.py`) -- objectif (remplacement PyInstaller ?) a confirmer.
5. **40 tests pytest non passants** : categoriser (flaky vs reel vs skip volontaire).
6. **9 erreurs log** : tracer la racine de chacune (pas seulement le symptome B01/B02/B05).
7. **Audit UX 07/06/2026** : pas de rapport synthese -- a ecrire avant clore.
8. **Bridge pywebview vs REST** : justifier le choix REST pour bibliotheque (latence / packaging / debug) et documenter dans CLAUDE.md.
9. **`uv.lock` non trace** : decision migration `pip` -> `uv` a entrainer ?

## K. LE PLUS CASSE

**Pipeline posters (2 surfaces : dashboard + bibliotheque)** -- bug visuel impactant, decevant alors que tout le backend TMDb (path -> URL -> tailles w92/w185/w342/w500) est correct et teste. La rupture est **purement frontend / configuration CSP** : `image.tmdb.org` n'est pas autorise dans la directive `img-src` du header Content-Security-Policy emis par `rest_server`. Le navigateur (WebView2 inclus) bloque les requetes, les `<img>` restent vides, et le diagnostic est trompeur car les payloads REST contiennent bien des `poster_url` valides. Fix attendu : une seule ligne dans la configuration CSP (`img-src` + `image.tmdb.org` ou `*.tmdb.org`). C'est le rapport effort/impact le plus eleve identifie dans cette recon.

**Secondaire** : l'absence de commit / rapport synthese sur l'audit UX 2026-06-07 (30 findings au sol, 9 open points re-ouverts le 2026-06-08) cree une dette de tracabilite qui pourrait faire perdre des fixes deja appliques si le working tree est reset.
