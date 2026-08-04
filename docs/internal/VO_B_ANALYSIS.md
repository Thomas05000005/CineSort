# VO-B Analysis : parallelisation de `_filter_dossiers_phase`

**Statut** : Analyse R2 (lecture seule, aucune modification code).
**Cible** : `cinesort/app/plan_support.py` L718 `_filter_dossiers_phase`.
**Objectif** : identifier la sous-phase strictement parallelisable et documenter le
plan de refactor sans toucher au code dans cette etape.

---

## 1. Cartographie de la boucle principale

La boucle `for idx, folder in enumerate(ctx.candidate_folders, start=1)` (L729)
execute pour chaque dossier candidat la sequence suivante :

| # | Operation | Localisation | Etat | Thread-safe ? |
|---|-----------|--------------|------|---------------|
| 1 | `ctx.wait_while_paused()` | L733 | mutation `ctx.pause_logged` + `time.sleep` cooperatif | NON (semantique sequentielle) |
| 2 | `ctx.check_cancel()` | L735 | mutation `ctx.cancel_logged` + log | NON |
| 3 | `ctx.scanned_total = idx` / `stats.folders_scanned += 1` | L737-738 | mutation `ctx.stats` | NON |
| 4 | `ctx.progress(idx, discover_total, str(folder))` | L740 | callback UI ordonne | NON (ordre strict) |
| 5 | `ctx.folders_seen_for_prune.append(str(folder))` | L741 | mutation liste partagee | NON |
| 6 | `rows_before = len(ctx.rows)` / `stats_snapshot_for_cache(ctx.stats)` | L743-744 | snapshot lecture | OUI mais inutile en parallele |
| 7 | `_try_apply_folder_cache(ctx, folder)` | L746 | lit `scan_index` (SQLite) + ecrit `ctx.rows`/`ctx.stats` | NON (SQLite handle + mutation) |
| 8 | `core_mod.iter_videos(cfg, folder, ...)` | L760-765 | **pur** : `os.scandir(folder)` + filtre, mutation optionnelle `stats.analyse_ignores_par_raison` | **OUI** si stats locales |
| 9 | branche `if not videos:` -> deltas + `_collect_non_video_extensions` + `persist_folder_cache` | L766-810 | mutation `ctx.stats` + I/O SQLite | NON |
| 10 | `_classify_and_plan_folder(ctx, folder, videos)` | L812 | dispatch vers `_plan_single` / `_plan_collection_item` / `_plan_tv_episode` | partiellement parallelisable (voir §3) |
| 11 | `ctx.persist_folder_cache(...)` | L813-818 | ecriture SQLite + serialisation rows | NON |

### Sous-arbre de `_classify_and_plan_folder` -> `_plan_item` (L1996)

| # | Sous-operation `_plan_item` | Type | Thread-safe ? |
|---|-----------------------------|------|---------------|
| a | `_try_lookup_row_cache` (lecture SQLite `scan_index`) | I/O DB lecture | NON (conn SQLite par thread requise) |
| b | `_resolve_folder_context` | pur | OUI |
| c | `core_mod.infer_name_year(folder_name, video.name)` | pur (regex) | OUI |
| d | `core_mod.build_candidates_from_name(...)` | pur | OUI |
| e | `core_mod.find_best_nfo_for_video(folder, video)` | I/O FS lecture (`folder.iterdir`) | OUI (FS read parallel) |
| f | `core_mod.parse_movie_nfo(nfo_path)` | I/O FS read + parse XML | OUI |
| g | `_build_nfo_candidates(...)` | pur sur nfo deja parse | OUI |
| h | `_augment_candidates_from_nfo_imdb` (tmdb.find_by_imdb) | **TMDb HTTP** | OUI via lock (cf §4) mais rate-limit a respecter |
| i | `_augment_candidates_from_nfo_tmdb_id` (tmdb.movie) | **TMDb HTTP** | idem |
| j | `_build_tmdb_fallback_candidates` (tmdb.search_movie) | **TMDb HTTP** | idem |
| k | `_apply_runtime_hard_filter_to_tmdb_cands` (tmdb.movie pour runtime) | TMDb HTTP optionnelle | idem |
| l | `_disambiguate_candidates` / `pick_best_candidate` | pur | OUI |
| m | `_build_resolved_row` / `_build_unresolved_row` | pur (sauf logs) | OUI |
| n | `_apply_subtitle_detection` (FS scandir sous-titres) | I/O FS lecture | OUI |
| o | `_apply_not_a_movie_detection` (regex) | pur | OUI |
| p | `_apply_integrity_check` (lecture binaire + check header) | I/O FS lecture | OUI |
| q | `_store_row_cache` (ecriture SQLite) | I/O DB ecriture | NON (serialiser ecritures) |

---

## 2. Decoupage cible : "Phase 1 pure" vs "Phase 2 sequentielle"

D'apres la cartographie, le decoupage exact pour preserver semantique + ordre UI
+ rate-limit TMDb est :

### Phase 1 (parallelisable) : pre-extraction **locale uniquement**

Pour chaque folder candidat, on calcule **sans toucher ctx, ni TMDb, ni cache DB** :

- `videos = iter_videos(cfg, folder, min_video_bytes, stats=local_stats_bucket)`
  - scandir local, filtre extensions, taille
  - on accumule les rejets dans un **dict local par folder** (`local_ignores_par_raison`)
- `non_video_exts = _collect_non_video_extensions(cfg, folder)` (utile uniquement si `videos == []`)
- branche classification preliminaire :
  - `is_tv_like = core_mod.looks_tv_like(folder, videos)`
  - `is_root_candidate = (folder.resolve() == cfg_root_resolved)`
  - `is_single_with_extras = core_mod.detect_single_with_extras(cfg, videos)`
- pour chaque video du folder, on pre-calcule la **partie pure** :
  - `folder_name, log_ctx, detected_edition = _resolve_folder_context(...)`
  - `name_year, name_year_reason, remaster_hint = core_mod.infer_name_year(...)`
  - `name_cands = core_mod.build_candidates_from_name(...)`
  - `nfo_path = core_mod.find_best_nfo_for_video(...)`
  - `nfo = core_mod.parse_movie_nfo(nfo_path)` (lecture + parse XML)
  - `nfo_cands, nfo_state = _build_nfo_candidates(...)` (pur sur nfo deja parse)

Sortie de Phase 1 par folder : un dataclass `LocalCandidate` capture cet etat.

### Phase 2 (sequentielle) : TMDb + ctx + UI + cache

Pour chaque `LocalCandidate` dans **l'ordre original** de `ctx.candidate_folders` :

1. `ctx.wait_while_paused()` puis `ctx.check_cancel()`.
2. `ctx.scanned_total = idx`, `ctx.stats.folders_scanned += 1`.
3. `ctx.progress(idx, discover_total, str(folder))`.
4. `ctx.folders_seen_for_prune.append(str(folder))`.
5. Fusion des `local_stats_bucket` du folder dans `ctx.stats` (deltas
   `ignore_extension`, `ignore_taille_min`, `ignore_nom_suspect`,
   `ignore_scandir_error`, `analyse_ignores_extensions`).
6. `_try_apply_folder_cache(ctx, folder)` -> si hit, `continue`. **WARNING** :
   le cache hit en Phase 2 rend l'extraction Phase 1 partiellement gaspillee.
   Mitigation : verifier `folder_sig` en Phase 1 et marquer `LocalCandidate.cache_hit_predicted = True`
   pour court-circuiter l'extraction (voir §5 risque CACHE-1).
7. Branche `videos == []` -> bumps stats + `persist_folder_cache`.
8. Sinon dispatch `_classify_and_plan_folder` mais **avec les candidats pre-calcules** :
   - `_plan_item` recoit deja `nfo`, `nfo_cands`, `name_cands` etc. via une
     entree alternative `_plan_item_from_local(local: LocalCandidate, ...)`.
   - Les appels TMDb (`_augment_candidates_from_nfo_imdb`,
     `_augment_candidates_from_nfo_tmdb_id`, `_build_tmdb_fallback_candidates`,
     `_apply_runtime_hard_filter_to_tmdb_cands`) restent en Phase 2.
9. `_apply_subtitle_detection`, `_apply_not_a_movie_detection`,
   `_apply_integrity_check` -> peuvent **rester en Phase 2** ou etre deplaces
   en Phase 1 (pures FS read). Garder en Phase 2 dans la v1 pour minimiser
   le scope du refactor (R2 mineur).
10. `_store_row_cache` + `persist_folder_cache`.

---

## 3. Sous-fonctions thread-safe vs non-thread-safe

### Pures / thread-safe (OK en parallele)

- `core_mod.iter_videos` -- si on passe un **stats local** (dict prive par worker).
- `core_mod.looks_tv_like` (regex sur noms).
- `core_mod.detect_single_with_extras` (lecture `stat().st_size` sur videos).
- `core_mod._collect_non_video_extensions` (FS iterdir local).
- `core_mod.infer_name_year` (regex pure).
- `core_mod.build_candidates_from_name` (pur).
- `core_mod.find_best_nfo_for_video` (FS iterdir local).
- `core_mod.parse_movie_nfo` (FS read + XML parse, pas d'etat partage).
- `_resolve_folder_context` (pur, derive du cfg + path).
- `_build_nfo_candidates` (pur sur nfo).
- `extract_edition`, `strip_edition` (regex).
- `core_mod.pick_best_candidate` (pur).

### Non thread-safe (DOIVENT rester en Phase 2 sequentielle)

- `ctx.rows.append/extend` (liste partagee, ordre = ordre de planification).
- `ctx.stats.*` mutations (counters).
- `ctx.folders_seen_for_prune.append`.
- `ctx.video_paths_seen.append`.
- `ctx.progress(...)` (UI **doit** voir 1->N strictement ordonne).
- `ctx.wait_while_paused()` / `ctx.check_cancel()` (semantique sequentielle).
- `ctx.persist_folder_cache(...)` -> ecrit `scan_index` SQLite ; **SQLite
  connection n'est PAS partageable entre threads** (sqlite3 check_same_thread).
- `_try_apply_folder_cache(ctx, folder)` -> lit `scan_index` ; meme contrainte.
- `_try_lookup_row_cache` / `_store_row_cache` -> idem SQLite.

### Conditionnellement thread-safe

- `TmdbClient.search_movie / search_tv / find_by_imdb / movie` :
  - `_lock` interne sur le cache OrderedDict (OK).
  - `requests.Session` avec `make_session_with_retry` : **thread-safe** seulement
    si la Session sous-jacente l'est. `requests.Session` est documente comme
    "not strictly thread-safe", mais le pattern courant (Session + Retry) tolere
    bien la concurrence moderee.
  - `CircuitBreaker.call` : a verifier ; si non lock-protected, ajouter lock.
  - **Rate limit TMDb** : 50 req / s par cle API. Avec `max_workers > 8` on
    risque de saturer. **Recommandation** : `max_workers` cap a 4-8 pour les
    appels TMDb. Si la Phase 1 est purement locale (sans TMDb), on peut
    paralleliser plus fort (16-32) sur l'I/O FS NAS.

---

## 4. Plan de refactor (a executer en phase ulterieure VO-B-IMPLEM)

### Dataclass `LocalCandidate`

```python
@dataclass
class LocalCandidate:
    folder: Path
    folder_sig: Optional[str]          # signature pour cache hit predicted
    cache_hit_predicted: bool          # si folder_sig hit en read-only
    videos: List[Path]                 # iter_videos resultat
    is_tv_like: bool
    is_root_candidate: bool
    is_single_with_extras: bool
    # Buckets locaux pour fusion en Phase 2 (pas de mutation ctx.stats)
    local_ignores_par_raison: Dict[str, int]
    local_non_video_exts: Dict[str, int]
    # Pre-extraction par video (ordre stable)
    per_video: List[VideoLocalContext]
    # Erreurs eventuelles (pour log en Phase 2)
    errors: List[str]


@dataclass
class VideoLocalContext:
    video: Path
    folder_name: str
    log_ctx: str
    detected_edition: Optional[str]
    name_year: Optional[int]
    name_year_reason: str
    remaster_hint: Optional[str]
    name_cands: List[Candidate]
    nfo_path: Optional[Path]
    nfo: Optional[NfoInfo]
    nfo_cands: List[Candidate]
    nfo_state: Dict[str, Any]
```

### Fonction pure `extract_local_candidate`

```python
def extract_local_candidate(
    cfg: Config,
    folder: Path,
    *,
    cfg_root_resolved: Path,
    cfg_sig: str,
    scan_index_readonly: Optional[ScanIndexReadOnly],  # voir §5 CACHE-1
) -> LocalCandidate:
    """Pure : ne mute aucune structure partagee. Peut etre appelee en parallele."""
```

### Boucle parallele en tete de `_filter_dossiers_phase`

```python
max_workers = max(1, int(getattr(cfg, "scan_max_workers", 1)))
discover_total = len(ctx.candidate_folders)

if max_workers == 1:
    # BACKWARD COMPAT STRICT : execution sequentielle inchangee
    for idx, folder in enumerate(ctx.candidate_folders, start=1):
        local = extract_local_candidate(...)
        _process_sequential(ctx, idx, discover_total, local)
else:
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # On preserve l'ordre original via list comprehension (futures soumises
        # dans l'ordre, recoltees via as_completed indexe par idx, mais
        # traitement sequentiel DECLENCHE en ordre 1..N).
        futures_in_order = [
            pool.submit(extract_local_candidate, ..., folder)
            for folder in ctx.candidate_folders
        ]
        for idx, fut in enumerate(futures_in_order, start=1):
            if ctx.wait_while_paused():
                # Annuler les futures non encore demarrees
                for f in futures_in_order[idx-1:]:
                    f.cancel()
                break
            if ctx.check_cancel():
                for f in futures_in_order[idx-1:]:
                    f.cancel()
                break
            try:
                local = fut.result()  # bloque jusqu'a ce que cette future soit prete
            except Exception as exc:
                ctx.log("WARN", f"extract_local_candidate failed for {ctx.candidate_folders[idx-1]}: {exc}")
                continue
            _process_sequential(ctx, idx, discover_total, local)
```

### Fonction sequentielle `_process_sequential`

Englobe tout le code Phase 2 (cache hit, fusion stats, classify, plan_item avec
LocalCandidate, persist_folder_cache).

---

## 5. Contraintes & risques identifies

### CONTRAINTE-1 : Ordre UI strict

`ctx.progress(idx, discover_total, str(folder))` **doit** etre emis dans
l'ordre 1, 2, ..., N. Garantie via `futures_in_order[idx]` + `fut.result()`
qui bloque jusqu'a disponibilite de cette future precise (pas `as_completed`).

### CONTRAINTE-2 : Rate limit TMDb

Phase 1 ne fait **aucun** appel TMDb. Aucune contrainte rate limit ajoutee
par la parallelisation. Phase 2 reste sequentielle donc rate limit inchange.

### CONTRAINTE-3 : SQLite thread-safety

`scan_index.get_incremental_folder_cache` et `upsert_incremental_folder_cache`
restent en Phase 2 sequentielle. Si on souhaite tester `folder_sig` en Phase 1
pour court-circuiter l'extraction (cache_hit_predicted), il faut soit :
- une connexion SQLite **par worker** (avec `check_same_thread=False`), soit
- un snapshot read-only des `(folder_path -> folder_sig)` pris en Phase 0
  avant le pool, puis lookup en memoire (dict).

Recommandation : option B (snapshot read-only) pour minimiser le risque.

### CONTRAINTE-4 : Pause cooperative

`ctx.wait_while_paused()` est verifie **avant** chaque traitement sequentiel
de Phase 2. Les workers Phase 1 ne verifient PAS la pause (acceptable : ils
finissent leur extraction puis se mettent en file pour la Phase 2).
Pour cancellation : `fut.cancel()` sur les futures non encore demarrees.

### CONTRAINTE-5 : Stats thread-safe

Les compteurs `stats.analyse_ignores_par_raison`, `stats.films_rejected_*`,
`stats.folders_rejected_*` sont incrementes via les helpers `_bump_stats_reject`
et `_stats_add_ignore`. Ces helpers **ne sont pas thread-safe** (lecture +
ecriture non atomique). Solution : chaque worker accumule dans son propre
`local_ignores_par_raison: Dict[str, int]` puis Phase 2 fait `ctx.stats.* += local.*`.

### CONTRAINTE-6 : Backward compat max_workers=1

L'option `cfg.scan_max_workers = 1` (default) **doit** garder le comportement
sequentiel strict actuel (pas de ThreadPoolExecutor du tout, branche `if max_workers == 1`).

### RISQUE CACHE-1 : extraction gaspillee sur cache hit

Si le cache folder hit en Phase 2 (`_try_apply_folder_cache`), toute l'extraction
Phase 1 (scandir, NFO parse) a ete faite pour rien. Sur un scan incremental
(99% hits), c'est une regression de perf. Mitigation : Phase 0 prend un snapshot
`{folder_path: folder_sig_existant}` depuis SQLite (single transaction lecture),
puis Phase 1 verifie : si `folder_sig_predicted == folder_sig_existant` ET
les rows cachees sont present (`scan_index.has_incremental_rows(folder_path)`),
on retourne un `LocalCandidate(cache_hit_predicted=True)` immediat. Phase 2
fait alors le replay des rows cachees sans rescanner.

### RISQUE TMDb-1 : ordre des appels TMDb change la sequence du cache

Le cache TMDb est `OrderedDict` LRU. Si l'ordre des appels change (parallelisme
en Phase 2 dans une iteration ulterieure), la sequence d'eviction LRU change.
**Non bloquant en VO-B** car Phase 2 reste sequentielle.

### RISQUE LOG-1 : ordre des logs

Les `ctx.log("WARN", ...)` emis depuis les helpers `_build_nfo_candidates`,
`_augment_candidates_from_nfo_imdb`, etc. ne sont plus emis dans l'ordre
1..N si on les emet en Phase 1. **Solution** : Phase 1 accumule les logs dans
`LocalCandidate.errors: List[str]`, Phase 2 les replay via `ctx.log()` dans
l'ordre.

---

## 6. Estimation gain perf

Sur NAS SMB, par folder candidat :
- `iter_videos` (scandir) : ~14ms NAS
- `find_best_nfo_for_video` (iterdir) : ~14ms
- `parse_movie_nfo` (read + parse) : ~5ms (si nfo present)
- Total Phase 1 (sans TMDb) : ~30ms/folder sequentiel

Avec `max_workers=8` sur 1000 folders : 30s -> ~4s. **Gain ~7x sur Phase 1**.

Phase 2 reste sequentielle (~200ms/folder avec TMDb), donc total
1000 folders : 200s -> 204s pre-refactor, 200s + 4s post-refactor = 204s.
**Gain global modeste si Phase 2 domine.**

**Conclusion** : le gain reel vient des bibliotheques **deja en cache TMDb**
(replan incremental) ou avec `cfg.enable_tmdb=False`. Dans ces cas Phase 2
descend a ~5ms/folder et Phase 1 devient dominante : 30s -> 4s, gain reel.

Pour les scans froids avec TMDb actif, le gain est marginal. **Recommandation** :
implementer VO-B-IMPLEM uniquement si l'usage cible inclut scans incremental
ou bibliotheques sans TMDb.

---

## 7. Test plan (pour VO-B-IMPLEM)

- [ ] Test backward compat : `scan_max_workers=1` -> diff vs baseline = 0 rows.
- [ ] Test parallele : `scan_max_workers=8` -> meme rows que sequentiel, meme
      ordre dans `ctx.rows`, meme stats finaux.
- [ ] Test progress ordering : `progress(idx, total)` recu en ordre 1..N strict.
- [ ] Test cancel mid-scan : annulation a idx=50 sur 1000 -> rows[50:] absent.
- [ ] Test pause/resume : pause a idx=50, resume, scan continue 51..1000.
- [ ] Test cache hit : bibliotheque pre-cachee, `cache_hit_predicted` -> pas
      d'extraction Phase 1, pas de regression de duree.
- [ ] Test SQLite thread-safety : aucune exception `ProgrammingError: SQLite
      objects created in a thread can only be used in that same thread`.
- [ ] Test stats merge : `films_rejected_ext` agrege correctement les
      contributions des workers Phase 1.

---

**Fin de l'analyse VO-B. Aucun code modifie dans cette phase.**
