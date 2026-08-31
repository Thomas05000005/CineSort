# Protocole observe.py - Gate fraicheur etat

> Source de verite operationnelle pour `scripts/observe.py --fresh`.
> Reference contextuelle : `docs/internal/DIAG_OBSERVE_FRESHNESS_2026-06-08.md`.
> Branche : `loop/correction-2026-06`.
> Statut : [OPERATIONNEL] depuis 2026-06-08 (etape 5 verrouillage piege).

## 1. Pourquoi un gate fraicheur ?

Le diag DIAG_OBSERVE_FRESHNESS_2026-06-08.md a demontre que les mesures
observe.py peuvent etre polluees silencieusement par trois sources de
staleness :

| Hypothese | Source | Symptome typique |
|-----------|--------|------------------|
| H1 | `dist/CineSort.exe` anterieur au code source | mesure d'un binaire pre-fix, fix invisible |
| H2 | DB SQLite + `runs/tri_films_*` derives | caches incrementaux, plans residuels, runs pollues |
| H4 | WebView2 userdata (`webview/EBWebView`) | sessionStorage/localStorage, Cache HTTP, cookies |

Sans gate, un meme `observe.py` peut produire des verdicts contradictoires
selon l'etat sedimente du LOCALAPPDATA cible.

## 2. Mode automatique : `--fresh`

```pwsh
python scripts/observe.py --library test_library --fresh --modes both
```

Effet :

1. **Pre-etape A (H1)** — `_rebuild_exe_if_needed()` ne builde PAS mais :
   - releve mtime de `dist/CineSort.exe` et le HEAD git (`git log -1 --format=%cI`) ;
   - marque `is_stale` si l'EXE est anterieur au HEAD ;
   - exporte `CINESORT_OBSERVE_FORCE_DEV=1` pour que `_detect_app_command`
     retourne systematiquement `python app.py --dev`.
2. **Pre-etape B (H2)** — `_reset_test_library_state()` :
   - sauve la DB en `cinesort.sqlite.bak_BEFORE_FRESH_<ts>` ;
   - `DELETE FROM <table> WHERE run_id IN (...)` pour toute table SQL avec
     une colonne `run_id` dont le `runs.root` matche `%test_library%` ;
   - `DELETE FROM probe_cache WHERE LOWER(path) LIKE '%test_library%'` ;
   - supprime les dossiers `runs/tri_films_*` referencant `test_library`
     (detection par lecture des 64 premiers Ko de `plan.jsonl`/`ui_log.txt`).
3. **Pre-etape C (H4)** — `_purge_webview2_userdata()` :
   - kill `msedgewebview2.exe` (best effort) ;
   - `shutil.rmtree(<LOCALAPPDATA>\CineSort\webview)`.

Toutes les actions sont **idempotentes** : un second `--fresh` sans rien faire
entre temps doit retourner `purged=False` (webview deja absent), `runs_deleted=0`,
`db_rows_deleted={}`.

## 3. Garde-fous donnees utilisateur (INVIOLABLE)

Le gate `--fresh` NE TOUCHE JAMAIS :

- `settings.json` (etat operateur : cle TMDb, token REST, roots) ;
- `omdb_cache.json`, `tmdb_cache.json` (caches partages indexes par titre) ;
- les donnees utilisateur reelles hors scope `test_library`, notamment
  `\\<nas>\Media\Films`, `\\<nas>\Media\downloads` et tout autre root configure.

Implementation : le reset DB filtre par `runs.root LIKE %test_library%`,
le reset disque par detection de `test_library` dans `plan.jsonl`/`ui_log.txt`.
Si la library passee a `--library` ne contient pas `test_library` dans son
chemin, **le reset DB est skip**, et `freshness_gate.json` consigne
`skipped_reasons: ["library hors scope test_library, donnees utilisateur PROTEGEES"]`.

## 4. Scope du LOCALAPPDATA cible

Par defaut, `--fresh` opere sur le state isole observe.py (`<out>/_state/`).
C'est la zone que `_make_state_dir_isolated()` cree avant lancement et que
le subprocess de l'app reutilise via `LOCALAPPDATA=<out>/_state/`.

Avec `--use-local-state`, `--fresh` cible `%LOCALAPPDATA%\CineSort` reel.
**Cas d'usage** : reproduire un bug en conditions reelles, ou nettoyer un
LOCALAPPDATA reel saturetuilisateur entre deux runs.

Le report `freshness_gate.json` enregistre `scope_note` :
- `"state isole observe.py (_state)"` (defaut),
- `"LOCALAPPDATA reel (--use-local-state)"`.

## 5. Procedure GATE manuelle

Si `--fresh` n'est pas disponible (vieille branche, contraintes), executer :

```pwsh
# H1 : EXE staleness (option 1 - rebuild)
pyinstaller --noconfirm CineSort.spec

# H1 : EXE staleness (option 2 - mode dev)
$env:CINESORT_OBSERVE_FORCE_DEV = "1"

# H2 : reset DB + runs scope test_library
$db = "$env:LOCALAPPDATA\CineSort\db\cinesort.sqlite"
Copy-Item $db "$db.bak_BEFORE_RESET_$(Get-Date -Format yyyyMMdd_HHmmss)"
# (DELETE manuel ou via sqlite3 sur runs WHERE root LIKE '%test_library%')

# H4 : purge WebView2 userdata
Stop-Process -Name msedgewebview2,CineSort -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$env:LOCALAPPDATA\CineSort\webview" -Recurse -Force -ErrorAction SilentlyContinue

# Lancement observe.py
python scripts/observe.py --library test_library --modes both
```

## 6. Lecture du gate report (`freshness_gate.json`)

Structure :

```json
{
  "ok": true,
  "scope_note": "state isole observe.py (_state)",
  "localappdata_target": "C:\\...\\_state",
  "library": "C:\\...\\test_library",
  "started_at": "2026-06-09T...",
  "h1_exe": {
    "ok": true,
    "exe_present": true,
    "exe_mtime": "2026-06-08T11:56:00",
    "head_commit_ts": "2026-06-08T18:45:00+02:00",
    "is_stale": true,
    "action": "force_dev_mode"
  },
  "h2_state": {
    "ok": true,
    "scope": "C:\\...\\test_library",
    "runs_deleted": 7,
    "db_rows_deleted": {"runs": 7, "quality_reports": 34, ...},
    "backup": "...\\cinesort.sqlite.bak_BEFORE_FRESH_...",
    "skipped_reasons": []
  },
  "h4_webview2": {
    "ok": true,
    "target": "C:\\...\\webview",
    "purged": true,
    "bytes_freed": 39_700_000
  },
  "ended_at": "2026-06-09T..."
}
```

Verdicts attendus :

- `h1_exe.is_stale == true` ET `action == "force_dev_mode"` :
  EXE pre-fix detecte, mode dev applique => H1 ECARTEE.
- `h2_state.ok == true` ET `skipped_reasons == []` :
  reset effectif, donnees utilisateur preservees => H2 ECARTEE.
- `h4_webview2.purged == true` (ou `note: "absent (rien a purger)"`) :
  userdata propre => H4 ECARTEE.

Si **les 3 H** sont ECARTEES et qu'observe.py renvoie ensuite des verdicts
POSTERS_ABSENTS sur des matchables : c'est une rupture aval (H3),
STOP / REMONTE conformement a la regle "H3 rupture produit aval = STOP REMONTE".

## 7. Marqueurs

- `[FIGE]`     : chemins LOCALAPPDATA, structure freshness_gate.json, ordre H1->H2->H4.
- `[HYPOTHESE]`: detection scope test_library par substring "test_library" dans le path.
- `[OPERATIONNEL]` : `--fresh` exposed depuis 2026-06-08, py_compile OK.

## 8. Limites connues

- Le gate ne resoud PAS la pre-condition TMDb (`tmdb_api_key` vide).
  Si la cle TMDb manque dans le `settings.json` isole, le scan court-circuite
  TMDb et `poster_url` reste `null` cote plan.jsonl, donc POSTERS_ABSENTS
  reste le verdict legitime. Voir `DIAG_OBSERVE_FRESHNESS_2026-06-08.md` 2e.
- Le gate ne seed PAS de `rest_api_token` dans le settings isole. Tant que
  l'isolation cree un `settings.json` ex-nihilo sans token, le dashboard
  detecte `_safeBearer: token absent` et n'emet aucun fetch REST.
  Workaround : `--use-local-state` (reutilise le settings.json reel).

## 9. AUCUN FIX SOURCE / AUCUNE PUBLICATION

Conformement aux memoires INVIOLABLES :
- AUCUN fichier sous `cinesort/` modifie. Le gate vit dans `scripts/`.
- AUCUNE publication (pas de tag, pas de release, pas de push).
- AUCUN secret commite : scrub() s'applique sur tout output, le backup DB
  reste local au LOCALAPPDATA cible (jamais commite).
