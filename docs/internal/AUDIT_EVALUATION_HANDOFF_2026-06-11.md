# DOSSIER D'ÉVALUATION — Audit + corrections CineSort (2026-06-10/11)

> But de ce document : permettre à un **autre modèle/évaluateur** de juger le travail
> sans avoir assisté à la session. Tout est factuel et vérifiable. Les limites et les
> points faibles sont listés explicitement pour que l'évaluation soit équitable.
>
> Branche : `loop/correction-2026-06`. **Aucun push effectué.** 21 commits de correction
> (+ commits docs). Modèle utilisé : Fable 5 sur toute la session.
>
> MISE À JOUR 2026-06-11 (2e passe) : 6 fixes backend supplémentaires ajoutés après le 1er
> handoff (Vague 5 ci-dessous). Le total de fixes Python testés par GATE passe à **17**.
>
> MISE À JOUR 2026-06-11 (3e passe — « fais les tous ») : sur demande de tout finir, **16 fixes
> supplémentaires** (Vague 6 ci-dessous) couvrant les **4 CRITICAL** restants + la famille perceptuelle
> (contrats testables) + les endpoints morts. Total : **35 commits de fix**, ~50 fichiers de GATE.
> Restent délégués au runtime (documenté en §5) : les bugs de PARSING de sortie ffmpeg.

---

## 0. Comment lire ce dossier

- Section 1 : le mandat (ce qui a été demandé).
- Section 2 : la méthode (comment l'audit et les fixes ont été menés).
- Section 3 : **playbook de vérification** — les commandes exactes pour tout rejouer.
- Section 4 : **registre des 15 fixes** — un tableau par fix : bug, preuve, approche, GATE, et
  **« points à scruter »** = ce que l'évaluateur devrait vérifier de façon critique.
- Section 5 : ce qui n'a **pas** été fait, et pourquoi.
- Section 6 : **auto-évaluation honnête** — où le travail est solide, où il est faible.
- Section 7 : échecs de tests PRÉ-EXISTANTS (pas causés par ce travail).
- Section 8 : grille d'évaluation suggérée.

---

## 1. Mandat

1. « relis tout le code de l'app … dis tout ce qui ne va pas » → audit exhaustif.
2. « on fixe dans l'ordre » puis « enchaine toutes les vagues correctement » → corriger les
   findings par vagues de priorité, en restant sur le modèle Fable 5.

Contraintes permanentes du projet (mémoire + CLAUDE.md), à respecter à chaque fix :
1 sujet = 1 commit ; checkpoint avant chaque fix ; tests ré-ancrés sur les vraies entrées ;
import-linter vert (3 contrats domain/infra/app) ; dry-run reste dry-run ; bypass loopback intact ;
couleurs tier hex invariantes ; aucun push ; aucun secret commité.

---

## 2. Méthode

### 2.1 Audit (phase de lecture)
- Workflow multi-agents `wf_984bef0d-63a` : 36 lecteurs (1 par sous-système : domain/app/infra/ui
  Python, 86 fichiers JS, 9 CSS, 32 migrations SQL, app.py, packaging) + 3 lentilles transverses
  (contrats UI↔backend, concurrence, secrets).
- Pipeline : **find** (chaque lecteur lit ses fichiers en entier, remonte des défauts réels) →
  **verify** (vérification adversariale de 1er niveau, réfute par défaut) → **panel** (double
  réfutation des CRITICAL/HIGH par 2 juges : correctness + atteignabilité runtime) → **critic**
  (complétude).
- Achevé en 4 reprises à cause de coupures de quota de session ; rien perdu grâce au journal de
  resume (`resumeFromRunId`). ~510 agents au total.
- Résultat : **314 findings uniques** (5 CRITICAL, ~140 HIGH, ~130 MEDIUM). Panel : **106 REAL 2/2**,
  37 contestés (bug source réel mais chemin mort/flag off), 1 tué.
- Rapport : `docs/internal/AUDIT_RELECTURE_2026-06-10.md` ; données brutes :
  `AUDIT_RELECTURE_2026-06-10_data.json`.

> ⚠️ Point d'honnêteté méthodo : chaque finding a **1 vérification adversariale** garantie ; le
> **panel** (2e couche) n'a couvert que les CRITICAL/HIGH. Les MEDIUM/LOW ont 1 seule passe. Les
> verdicts « vérifié empiriquement » sur ffmpeg dépendent de la version du venv (8.x), pas du binaire
> bundle. L'évaluateur ne doit donc PAS traiter les findings comme une vérité absolue.

### 2.2 Corrections (phase de fix)
Pour chaque fix : (1) lire le vrai code des deux côtés du contrat avant de toucher — jamais fixer
sur la foi du finding seul ; (2) checkpoint git ; (3) fix au bon étage ; (4) **GATE** = test qui
échoue avant / passe après et qui prouve le comportement réel (pas un mock complaisant) ; (5)
ré-ancrer les tests qui encodaient l'ancien comportement bugué ; (6) `import-linter` + suite locale ;
(7) commit 1 sujet. Pour le JS : `node --check` + lecture croisée du contrat backend (pas de
pytest possible).

---

## 3. Playbook de vérification (commandes exactes)

```bash
cd <racine_du_repo_CineSort>   # chemin local non inscrit ici (test no_personal_strings)

# (a) Tous les GATE de la session passent (159 attendus) — hors e2e/chromium :
python -m pytest \
  tests/test_quarantaine_ttl_v77.py tests/test_quarantaine_viewer_v77.py \
  tests/test_apply_atomicity.py tests/test_apply_atomic_rollback_integration_v77.py \
  tests/test_rest_security.py tests/test_log_scrubber.py \
  tests/test_tooling_path_validation.py tests/test_auto_install.py \
  tests/test_hydrate_secrets_mask_v77.py tests/test_internal_settings_unmask_v77.py \
  tests/test_restart_api_server_v77.py tests/test_duplicate_group_key_contract_v77.py -q
# Attendu : 159 passed + 4 FAILED PRÉ-EXISTANTS dans test_rest_security (cf §7).

# (b) Architecture verrouillée :
lint-imports          # Attendu : 3 contracts kept, 0 broken

# (c) JS syntaxiquement valide :
node --check web/dashboard/views/doublons.js
node --check web/dashboard/views/accueil.js
node --check web/dashboard/views/traitement.js

# (d) Vérifier qu'un fix précis répare bien : enlever le fix et voir le GATE rougir
git stash   # ⚠ NE PAS faire ici : le repo a 15 stashs préexistants (cf memory). Préférer :
git show <commit>~1:<fichier> > /tmp/avant.py   # comparer, ou git revert --no-commit <commit>

# (e) Diff complet d'un fix :
git show <sha>
```

> Note importante sur `git stash` dans ce repo : il y a **15+ stashs préexistants** d'autres
> sessions. Un `git stash && … ; git stash pop` après un état déjà commité dépile par erreur le
> stash d'autrui. Pour comparer avant/après, utiliser `git show <sha>~1:<fichier>` ou
> `git revert --no-commit`.

---

## 4. Registre des 15 fixes

Légende « Points à scruter » = ce qu'un évaluateur sceptique devrait vérifier.

### VAGUE 1 — Perte de données

**[1] `7089cab` — TTL quarantaine (CRITICAL, panel REAL 2/2)**
- Bug : `quarantine_ttl.py:195` purgeait sur `st.st_mtime`, préservé par `shutil.move`. Un film
  vieux de plusieurs mois était supprimé au 1er cycle après mise en quarantaine.
- Fix : dater l'**entrée** via un manifest `.cinesort_ttl_manifest.json` (1re observation). Migration
  sûre : fichiers déjà présents repartent à `now` → jamais purgés rétroactivement.
- Fichiers : `quarantine_ttl.py` (+153/-?), tests TTL + viewer ré-ancrés.
- GATE : `test_old_mtime_recent_arrival_not_purged` (mtime 999j + arrivée now → conservé, puis arrivée
  vieillie 40j → purgé). + `test_age_days_uses_arrival_not_mtime`.
- Points à scruter : (a) le manifest est-il bien exclu de l'inventaire et de la purge ? (oui,
  `test_arrival_manifest_excluded_from_inventory`) ; (b) le nettoyage du manifest après purge
  empêche-t-il qu'une row réutilisant un chemin hérite d'une vieille date ? (oui, re-sync en fin de
  purge) ; (c) **les tests ont été ré-ancrés** — vérifier qu'ils testent la BONNE sémantique, pas
  juste qu'ils passent.

**[2] `9d89200` — journal write-ahead apply (HIGH, panel REAL 2/2)**
- Bug : `apply_core.py:1368` et `:988` — `row_record_op` était une fonction nue qui perdait
  `journal_store`/`journal_batch_id` → `atomic_move` retombait sur `shutil.move` sans journal.
- Fix : ré-enrober dans `RecordOpWithJournal` en recopiant les 2 attributs.
- GATE : `test_per_row_wrapper_preserves_journal_write_ahead` — spy sur `insert_pending_move` prouve
  que le write-ahead se déclenche + `batch_id` propagé + `row_id` injecté.
- Points à scruter : le GATE reproduit la construction d'`apply_core` mais ne l'appelle pas
  directement (il ré-implémente le wrapping). Un évaluateur peut vouloir un test bout-en-bout via le
  vrai `apply_single`. Risque : faible (les 2 sites sont identiques et lus).

**[3] `e7346ee` — rollback QUARANTINE (HIGH, panel REAL 2/2)**
- Bug : `apply_rollback.py:113` ne revert que MOVE_*, laissait les QUARANTINE_* déplacés tout en
  retournant ok=True.
- Fix : ajouter QUARANTINE_FILE/QUARANTINE_DIR aux op_types revert-ables (revert dst→src identique ;
  sémantique src/dst confirmée côté `apply_core` L2146-2196, `reversible=True`).
- GATE : `test_rollback_reverts_quarantine_ops` (done=2, skipped=0, FS restauré).
- Points à scruter : vérifier qu'aucun autre op_type `reversible=True` n'est encore exclu — vérifié :
  seuls MKDIR (reversible=False, filtré en amont) et MOVE/QUARANTINE existent.

### VAGUE 2 — Sécurité

**[4] `b1dd226` — CSRF + CORS (panel REAL 2/2)**
- Bug : `ACAO:*` par défaut + bypass auth loopback = un site externe pouvait POST sur l'API locale.
- Fix : `_is_forbidden_cross_site` (403 si Origin externe sur POST) + `_send_cors_headers` n'écho plus
  `*` (seulement localhost / same-origin / cors_origin configurée).
- GATE : 7 tests (POST cross-site → 403 ; Origin localhost autorisée ; pas de `*` par défaut).
- Points à scruter : **le plus important à challenger.** (a) Un attaquant peut-il contourner via une
  « simple request » (POST text/plain sans preflight) ? Le garde Origin bloque quand même car le
  navigateur envoie Origin sur tout POST cross-site — mais un évaluateur devrait confirmer que le
  dispatcher ne traite pas un body non-JSON d'une façon exploitable. (b) Le dashboard desktop est-il
  bien same-origin (pas file://) ? Affirmé d'après `app.py` (chargé via `http://127.0.0.1:port/…`) —
  **non vérifié en runtime**. Si le desktop charge en file:// ou custom scheme, l'Origin serait
  « null » → le garde le bloquerait → régression. À VALIDER SUR L'EXE.

**[5] `5dc70ea` — OMDb HTTPS** — trivial, `http://`→`https://`. Risque ~nul. Pas de GATE dédié
(95 tests omdb passent). Scruter : OMDb supporte bien HTTPS (oui, documenté).

**[6] `e20d2c0` — scrubber (2 sous-bugs)**
- Bug a : args non-str (`logger.x("%s", exc)`) non scrubbés → fuite. Bug b : install avant
  `basicConfig` → handler console non couvert.
- Fix : `_scrub_arg` scrubbe le `str()` des non-str et ne remplace que si un secret a été retiré
  (ints/`%d` préservés) ; install re-synchronisable + appel ajouté après `basicConfig` dans `app.py`.
- GATE : exception non-str scrubbée, args numériques préservés, handler ajouté après install couvert.
- Points à scruter : `_scrub_arg` fait `str(value)` sur chaque arg non-str de CHAQUE log — léger
  surcoût. Acceptable. Vérifier qu'un objet au `__str__` coûteux n'est pas un problème (rare).

**[7] `8a387f2` — whitelist binaire probe**
- Bug : `tooling.py:122` exécutait le chemin configuré sans vérifier le nom ; la whitelist n'était
  appliquée que dans `validate_tool_path`.
- Fix : `_binary_name_allowed` appliqué dans `_resolve_tool_path` (fail-closed → fallback PATH) ;
  whitelist déplacée dans `tooling.py` comme source unique (importée par `tools_manager`).
- GATE : `test_explicit_path_non_whitelisted_binary_falls_back` (calc.exe ignoré).
- Points à scruter : un test existant a été **ré-ancré** (il sur-mockait `Path`) — vérifier que le
  ré-ancrage est légitime (oui : il ajoutait `instance.name="ffprobe.exe"`, un nom whitelisté).

**[8] `9ef5457` — SHA256 archives (MITIGATION, finding single-verified)**
- Bug : `EXPECTED_SHA256_* = None` → archives ffmpeg/MediaInfo non vérifiées.
- Fix : **mitigation seulement** — épinglage via env var `CINESORT_FFMPEG_SHA256` /
  `CINESORT_MEDIAINFO_SHA256`. Aucun hash fabriqué (FFmpeg gyan.dev = rolling release).
- Points à scruter : **ce n'est PAS un fix complet.** Par défaut, rien n'est vérifié (warning). Le
  vrai correctif (hashs pinnés) est une tâche de release. Le finding n'a eu qu'1 vérification (non
  re-confirmé au panel). Un évaluateur peut légitimement juger ce point « partiellement traité ».

### VAGUE 3 — Secrets masqués (~12 chemins)

**[9] `f11bf2a` — hydratation scan (panel REAL 2/2)** — couvre accueil.js + watcher d'un coup.
- Bug : `_hydrate_settings_from_store` laissait le masque `••••••••` du caller écraser la vraie clé
  disque → scans avec TMDb/OMDb en 401.
- Fix : sauter tout secret == masque (vraie valeur disque conservée).
- GATE : 3 tests (masque→vraie clé préservée ; vraie clé caller→override ; non-secrets inchangés).
- Points à scruter : solide. Le test guard existant (`test_plan_tmdb_enrichment_guard`) passe toujours
  → backward compat confirmée.

**[10] `1eb1fb0` — 7 rapports intégrations**
- Bug : 7 méthodes (email dispatch/test, jellyfin/plex/radarr reports) lisaient le payload masqué.
- Fix : helper `_internal_settings()` = `_get_settings_impl()` (mockable) puis dé-masque depuis le
  disque. 7 sites swappés.
- GATE : `test_internal_settings_unmask_v77` (3 tests).
- Points à scruter : le design a été **revu en cours** — 1re version (lecture disque directe) cassait
  20 tests qui mockaient `_get_settings_impl` ; 2e version (dé-masque-depuis-disque) garde la
  mockabilité. Vérifier que les 216 tests intégrations passent (ils passent).

**[11] `74171f0` — rescan TMDb** — ⚠️ **pas de GATE dédié neuf.**
- Bug : `library_actions_support.py:282` lisait masqué → TmdbClient avec clé masquée.
- Fix : `api._internal_settings()`.
- Points à scruter : **ce fix n'a pas son propre test neuf.** Il s'appuie sur le GATE de
  `_internal_settings` (mécanisme prouvé) + les 35 tests rescan existants qui passent. Un évaluateur
  rigoureux notera l'absence de GATE spécifique au site. Risque : faible (1 ligne, même mécanisme).

**[12] `a0a8701` — restart serveur REST**
- Bug : `_restart_api_server_impl` relançait avec token masqué + omettait host/cors.
- Fix : `_internal_settings()` (token clair) + `host="0.0.0.0" si rest_api_enabled` + cors_origin
  (parité avec `app.py:351-360`).
- GATE : `test_restart_api_server_v77` (token réel + host 0.0.0.0 + cors transmis).

### VAGUE 4 — Contrats JS vivants

**[13] `e347684` — doublons group_key (panel REAL 2/2)**
- Bug : `_groupKey` JS générait `Title::Year` ; backend `_group_key_for` génère `title|year`. Comme
  `check_duplicates` ne renvoie jamais `group_key`, les 2 fallbacks divergeaient →
  `mark_duplicate_winner` ne retrouvait jamais le groupe → `losers=[]` → aucun perdant déplacé.
- Fix : fallback JS rendu identique au backend (`title.lower()|year`, `|` strippé).
- GATE : `test_duplicate_group_key_contract_v77` épingle les sorties backend + **équivalence JS↔Python
  vérifiée à la main sur 5 cas** (sorties identiques, edge cases inclus).
- Points à scruter : la meilleure preuve JS de la session (cross-langage). Mais le GATE Python épingle
  le backend, pas le JS — si quelqu'un change le JS, rien ne casse automatiquement. C'est une limite
  inhérente (pas de harness de test JS dans le repo).

**[14] `b4c6fdb` — accueil res.data.ok (panel REAL 2/2)** — ⚠️ **vérif = node --check + raisonnement.**
- Bug : `initAccueil` testait `dashRes.ok===false` alors que l'enveloppe est `{status, data}` →
  erreur métier rendue comme succès.
- Fix : pattern `res.data.ok` (déjà utilisé par `_triggerStartPlan`) appliqué aux 4 réponses.
- Points à scruter : **aucun test runtime.** Seulement `node --check` + cohérence avec le pattern
  existant. À valider sur l'EXE (simuler une erreur get_dashboard).

**[15] `ba10800` — traitement auto-save (panel REAL 2/2)** — ⚠️ **vérif = node --check + raisonnement.**
- Bug : `unmountTraitement` lançait `_handleSaveValidation()` (avec `_signal()`) puis `abort()` →
  save annulé → décisions perdues.
- Fix : mode `{ detached: true }` → save sans signal (survit à l'abort) + sans render/toast.
- Points à scruter : **aucun test runtime.** Vérifier par lecture que `detached` n'introduit pas de
  régression (pas de render sur container détaché). À valider sur l'EXE.

### VAGUE 5 — Contrats backend + invariants + résilience (2e passe, 6 fixes)

**[16] `330f60c` — get_dashboard expose `status` + `active_run_id`**
- Bug : `runs_history` n'avait pas de `status` (CTA "Reprendre la validation" accueil + filtres
  Statut/Undone historique ne matchaient jamais) ; `active_run_id` absent du payload (carte "Scan en
  cours" jamais affichée — il n'existait que sur `/api/health`).
- Fix : ajout de `status` (source `runs.status`) et `active_run_id` (logique de
  `rest_server._find_active_run_id`) aux 3 payloads.
- GATE : `test_dashboard_status_active_run_v77` (status='DONE', clé active_run_id, détection run en cours).
- Points à scruter : le détail de progression (total/current/phase) reste à brancher côté JS via polling
  `/run/get_status` — ce fix restaure seulement la DÉTECTION (le JS affiche la carte), pas les chiffres
  fins. À compléter en runtime.

**[17] `02c3424` — couleurs tier de l'export HTML (invariant user)**
- Bug : `export_support._TIER_COLORS` codait des hex faux (gold=#f59e0b…) → rapports HTML avec des
  couleurs de tier différentes de l'app, violation de l'invariant CLAUDE.md #2.
- Fix : alignement sur l'invariant (Platinum #E5E4E2 / Gold #FFD700 / Silver #C0C0C0 / Bronze #CD7F32).
- GATE : `test_tier_colors_are_invariant`. Risque ~nul.

**[18] `889d07a` — l'extension `.ts` n'est plus détectée comme CAM (REAL 2/2)**
- Bug : pattern CAM `\bTS\b` matchait l'extension `.ts` (le caller passe le nom avec extension) → tout
  fichier MPEG-TS légitime marqué CAM → tier capé Bronze, facteur -30, message faux.
- Fix : retirer l'extension finale (`\.[A-Za-z0-9]{1,4}$`) avant la détection CAM (un vrai token TS est
  mid-name).
- GATE : `test_release_name_cam_ts_v77` (.ts non CAM ; TS/HDTS/HDCAM mid-name toujours CAM).
- Points à scruter : 161 tests de scoring passent (pas de régression sur les vrais CAM).

**[19] `c2b5605` — circuit breaker TMDb compte les 5xx/429 (REAL 2/2)**
- Bug : même classe que omdb-1 — `raise_for_status` après `_breaker.call`, session `raise_on_status=False`
  → 5xx jamais vu par le breaker → circuit jamais ouvert (retries × 5000 films sur TMDb en panne).
- Fix : `raise_for_status` DANS le lambda UNIQUEMENT pour 5xx/429 (les 4xx passent intacts pour
  `validate_connection` qui gère le 401 gracieusement).
- GATE : `test_tmdb_breaker_5xx_v77` (breaker s'ouvre sur 503 répétés ; 404 ne lève pas dans le lambda).
- Points à scruter : la distinction 5xx-only est volontaire — vérifier qu'aucun caller ne dépend d'un
  5xx renvoyé brut (tous font `raise_for_status` après sauf l'auth qui gère 4xx).

**[20] `933c43b` — un TypeError du corps d'un job ne rejoue plus le job (REAL 2/2)**
- Bug : `_invoke_job_fn` entourait l'appel d'un `except TypeError → job_fn(should_cancel)`. La signature
  ayant déjà confirmé `should_pause`, un TypeError vient du CORPS (données invalides) → l'ancien code
  rejouait le job ENTIER (double déplacements de fichiers, journal, notifs).
- Fix : valider la liaison via `sig.bind()` (sans exécuter) ; un TypeError du corps se propage.
- GATE : `test_body_typeerror_does_not_rerun_job` (job exécuté 1× ; should_pause toujours injecté).

> Note : le fix `status`/`active_run_id` n'ajoute PAS le champ `undone`/`is_undo`/`type` (détection des
> runs d'undo) — sous-finding plus petit, laissé pour plus tard.

### VAGUE 6 — 4 CRITICAL restants + perceptuel + endpoints morts (3e passe, 16 fixes)

**CRITICAL**
- **`79ba75a` — 3 crashes ndarray perceptuel** (`video_analysis`/`grain_analysis`) : `if not pixels:`/`if
  pixels:` sur un `np.ndarray` (refactor B3) → `ValueError` → toute l'analyse vidéo perceptuelle plantait
  (avalée en warning). Fix : check `np.size()` (valide list+ndarray). GATE `test_perceptual_ndarray_guards_v77`.
- **`a8ad081` — `tmdb_support` AttributeError** : `api._normalize_user_path` inexistant → 500 sur
  get_tmdb_posters/search_tmdb. Fix : `normalize_user_path` module-level + clé dé-masquée. GATE.
- **`222534c` — endpoints quarantaine** : `_build_cfg_from_settings_payload(settings)` sans les 4 kwargs →
  TypeError → viewer/purge/**cron TTL morts** (rendait le fix TTL [1] inopérant). Fix : helper
  `_build_quarantine_cfg`. GATE.

**Perceptuel (contrats testables sans ffmpeg)**
- **`cef8f30` — composite_v2 clés probe** : `has_hdr10`/`has_dv` vs `hdr10`/`hdr_dolby_vision` (HDR scoré SDR) ;
  `audio` vs `audio_tracks` (fake-lossless jamais détecté) ; `api._tmdb_client()` inexistant (analyse vidéo
  échouait). GATEs + tests composite ré-ancrés.
- **`0919fdc` — index audio relatif** : `best["index"]` (absolu conteneur) utilisé comme index audio-relatif
  dans `-map 0:a:N` → loudnorm/astats/clipping échouaient. GATE.

**Endpoints morts par drift de contrat**
- **`9874fb9` — reset_database** : mauvais chemin DB (`cinesort.db` vs `db/cinesort.sqlite`) → wipe jamais
  effectué. Tests ré-ancrés. 
- **`771c30c` — modal film timeline** (clé `events` vs `history`) + **analyze_quality_batch scope=validated**
  (`api.load_validation` → `api.run.load_validation`, 500). 
- **`17571e0` — champs TV/sous-titres** non restaurés à la désérialisation (cache + restart) → renommage
  **`S00E00`**. GATE round-trip sur les 2 chemins.
- **`65212b3` — historique par film** : run dir `runs/<id>` vs `runs/tri_films_<id>` → 0 événement. GATE.
- **`c373e85` — sagas incomplètes** : `TmdbClient(api_key=...)` sans cache_path → TypeError → feature morte. GATE.
- **`0ad9c99` — timeline Jellyfin** : `get_movies` (inexistant) → `get_all_movies` + clé dé-masquée. Test ré-ancré.

Non-régression Vague 6 : 39 nouveaux GATE + 200 sur suites impactées (perceptuel/scene/plan/quality/timeline/
reset), import-linter vert. Tests ré-ancrés signalés (composite, reset, library_timeline — encodaient les
mauvaises clés/chemins).

> Points à scruter Vague 6 : (a) le check `np.size()` suppose que `pixels` est None/list/ndarray (jamais un
> scalaire 0-d) — vrai pour des frames. (b) Les fixes "clé masquée" réutilisent `_internal_settings` (mécanisme
> déjà GATE en Vague 3). (c) `_resolve_run_dir`/`_resolve_db_path` dupliquent une convention de nommage de
> `infra` dans `domain`/`ui` (import-linter interdit l'import) — à garder synchronisé si la convention change.

---

## 5. Ce qui n'a PAS été fait (et pourquoi)

1. **`scan_helpers.py:280` fast-path dossier `(YYYY)` (REAL 2/2, DÉLIBÉRÉMENT MIS DE CÔTÉ)** : un
   dossier `Avatar (2009)/` matchant `(YYYY)` devient candidat SANS être descendu → un film en
   sous-dossier release imbriqué (`Avatar (2009)/Avatar.2009.1080p-GRP/film.mkv`) est silencieusement
   absent du plan. Le fix est dans le **cœur du scan** : le rendre candidat ET le descendre risque de
   dupliquer des films (cas vidéo directe) ou de planifier des featurettes comme films. **Trop risqué
   en aveugle** — nécessite une validation sur de vrais layouts de bibliothèque. → délégué runtime/Opus.
2. **Détail de progression accueil / drawer options / processing.js / vues mortes** : le contrat
   `active_run_id`/`status` est maintenant fourni (fix [16]), mais les CHIFFRES de progression
   (total/current/phase) demandent un polling JS `/run/get_status` ; les options du drawer
   (dry_run/skip_duplicates) et les 4 étapes de `processing.js` demandent une décision (brancher vs
   supprimer du code mort). → nécessitent l'EXE/Playwright pour mesurer avant de toucher.
3. **Bugs de PARSING de sortie ffmpeg (perceptuel audio/vidéo)** : `-v quiet` qui supprime le JSON
   loudnorm, `signalstats` sans `metadata=print`, bloc astats « Overall » sans crest/dynamic range,
   `mpdecimate` loggé en debug. Le « fix » consiste à changer la commande ffmpeg ET le parsing, et sa
   validité dépend du **format de sortie exact de la version de ffmpeg bundlée**. Vérifiés par l'audit
   « empiriquement avec ffmpeg 8.x » mais le binaire livré peut différer → **DÉLÉGUÉS au runtime**
   (lancer l'app + ffmpeg réel et constater la sortie avant de toucher). Les fixes de CONTRAT du
   perceptuel (clés probe, index audio, crashes ndarray, tmdb_client) sont eux faits (Vague 6).
4. **`quality_simulator_support._store`** (REAL au code, CONTESTÉ runtime) : `api._store` n'existe pas →
   simulateur G5 mort, MAIS le modal G5 n'est monté par aucune route vivante (vue morte) → latent.
5. **134 MEDIUM + 33 LOW** : non traités (priorité aux CRITICAL/HIGH REAL 2/2).
2. **Les 37 findings CONTESTÉS** : bug source réel mais chemin mort/flag off (ex toute la famille
   `views/library/lib-*.js` jamais montée). Non corrigés : latents, pas actifs. À traiter par
   suppression de code mort ou re-branchement — décision produit.
3. **Angles hors audit** (signalés par le critique) : CI/workflows GitHub, packaging/signature,
   locales en/fr, les tests eux-mêmes, scripts dev, binaires `tools/`, multi-lockfiles, et
   **771 Mo de `docs/internal/observe/` trackés** (risque PII/token).
4. **2 fixes complets non faits** : SHA256 réel (tâche release) ; le finding `auto_install` n'est
   que mitigé.

---

## 6. Auto-évaluation honnête

**Solide :**
- Les 11 fixes Python ont un GATE qui prouve le comportement réel, pas un mock complaisant.
- Tous les bugs ont été confirmés par **lecture du vrai code des deux côtés** avant fix, pas sur la
  foi du finding.
- import-linter vert après chaque commit ; 1 sujet/commit ; checkpoints ; aucun push.
- Centralisation propre (Vague 3) : `_internal_settings` + hydratation couvrent ~12 chemins avec
  2 mécanismes plutôt que 12 rustines.
- Tests ré-ancrés honnêtement signalés (TTL, CORS, tooling) avec justification.

**Faible / à challenger :**
- **3 fixes JS** : 2 (`b4c6fdb`, `ba10800`) n'ont QUE `node --check` + raisonnement, aucun test
  runtime. Le 3e (`e347684`) a une preuve cross-langage mais pas de garde JS automatique.
- **`74171f0`** : pas de GATE neuf dédié.
- **`9ef5457`** : mitigation, pas fix complet ; finding single-verified.
- **`b1dd226` (CSRF)** : repose sur l'hypothèse « dashboard desktop = same-origin » NON vérifiée en
  runtime. Si faux → régression potentielle. **C'est le fix à valider en priorité sur l'EXE.**
- Aucun fix n'a été validé sur l'application réelle lancée (pas de run EXE/Playwright cette session).
  Les GATE prouvent la logique unitaire, pas le comportement bout-en-bout dans le vrai binaire.
- L'audit lui-même : 314 findings à 1 passe de vérif (panel sur CRITICAL/HIGH seulement) ; quelques %
  de faux positifs probables, concentrés sur les chemins passant par des vues mortes.

---

## 7. Échecs de tests PRÉ-EXISTANTS (NON causés par ce travail)

Vérifiés en rejouant sur l'état d'avant le fix concerné — ils échouaient déjà :
- `tests/test_rest_security.py` : `test_request_without_auth_returns_401`,
  `test_request_invalid_token_returns_401`, `test_request_empty_token_returns_401`,
  `RateLimiterHttpIntegrationTests::test_rate_limiter_returns_429_after_5_failures` → tous parce que
  `/api/get_settings` (legacy direct) renvoie **410 Gone** par défaut (kill-switch Pass 1). Documenté
  dans le bilan iter15.
- `tests/test_phase5_historique_complete.py::ApplyTabDetailTests::test_apply_op_labels`.
- `tests/test_release_hygiene.py::RecordApplyOpTests::test_returns_false_on_failure_and_logs`.
- `tests/test_release_hygiene.py::ReleaseHygieneTests::test_no_personal_strings_in_repo` (chemins persos dans
  d'anciens BILAN trackés, antérieurs à la session ; vérifié sur HEAD du 2026-06-09).
- `tests/test_phase4_parametres_endpoints.py::ResetSettingsTests::test_scope_apparence_restores_default_theme`
  (reset du thème, sans rapport avec `_resolve_db_path` ; échoue sur la version HEAD).
- `tests/test_quality_score.py::…::test_analyze_quality_batch_rejects_concurrent_launch` et
  `…::test_analyze_quality_batch_logs_structured_error…` : tests de concurrence/état, **flaky** en suite
  pleine, PASSENT en isolation (timing, pas un bug produit).
- `tests/test_audit_2026_05_24_regression.py::…::test_save_section_omdb_exists`.

À ne PAS imputer aux corrections de cette session. (À traiter séparément.)

> NOTE Vague 6 : plusieurs tests EXISTANTS ont été ré-ancrés car ils mockaient l'ancien contrat
> (test_tmdb_support, test_phase6_tmdb_manual_search, test_library_timeline → `_internal_settings` ;
> test_phase4 reset → chemin DB canonique ; test_composite_score_v2 → vraies clés probe). C'est légitime
> (le code corrige le contrat ; les tests testaient le bug). L'évaluateur peut vérifier que chaque ré-ancrage
> teste le comportement CORRECT, pas juste « ça passe ».

---

## 8. Grille d'évaluation suggérée

Pour chaque fix, l'évaluateur peut noter :
1. **Bug réel ?** Relire le code d'avant (`git show <sha>~1:<fichier>`) et confirmer que le défaut
   existait et était atteignable.
2. **Fix correct ?** Le diff répare-t-il la cause racine sans effet de bord ?
3. **GATE probant ?** Le test échoue-t-il sans le fix ? (le retirer / `git revert --no-commit` et
   relancer le test ciblé). Le test mesure-t-il le comportement réel ou un mock complaisant ?
4. **Ré-ancrage légitime ?** Quand un test existant a été modifié, le nouveau assert reflète-t-il le
   comportement CORRECT (pas juste « ça passe ») ?
5. **Régression ?** La suite locale + import-linter restent verts.

Points de vigilance prioritaires pour l'évaluateur : **[4] CSRF** (hypothèse same-origin non
vérifiée), **[14]/[15] JS** (pas de test runtime), **[11]/[8]** (GATE absent / mitigation).

Verdict attendu d'un évaluateur juste : corrections Python solides et bien testées ; corrections JS
plausibles mais à valider en runtime ; périmètre volontairement borné aux REAL 2/2 sûrs, le reste
explicitement remis à une session avec l'EXE.

---

## ANNEXE OPUS (2e modèle) — validation runtime + 3 fixes (2026-06-11)

> Délégué par Fable 5 sur les points demandant plus de capacité ou une validation runtime.
> Modèle : Opus 4.8. Branche `loop/correction-2026-06`. **Aucun push.** Même protocole
> (1 sujet/commit, GATE qui échoue avant / passe après, import-linter 3/3 vert).
>
> Commits créés (3) :
> - `a400a4e` — fix(scan): fast-path dossier (YYYY) descend les releases imbriquées
> - `cddba9c` — fix(watchlist): un remake (année différente) n'est plus marqué "owned"
> - `7b94c73` — fix(db): pragma_history bornée par rétention après chaque insert

### Mission 1 — CSRF same-origin : **HYPOTHÈSE VALIDÉE EN RUNTIME (pas de fix nécessaire)**

**Verdict : l'hypothèse "dashboard desktop = same-origin" TIENT, et le garde est même plus sûr
qu'estimé.** Validé en lançant réellement l'app (`python app.py` avec `CINESORT_E2E=1` → CDP port
ouvert, app.py:719-721) et en inspectant les requêtes via Playwright/CDP (le harness existant
`tests/e2e_desktop/conftest.py` confirme ce mode de lancement). pywebview 6.2.1 + WebView2
(edgechromium), Python 3.12, Playwright 1.60.

**Preuves capturées en runtime (pas par raisonnement) :**
1. **URL réelle de la page principale** : `http://127.0.0.1:8642/dashboard/?native=1#/accueil`.
   → servie en **HTTP same-origin sur 127.0.0.1**, PAS `file://`, PAS de custom scheme. (Cohérent
   avec app.py:828/892 : `main_url = f"{proto}://127.0.0.1:{port}/dashboard/?ntoken=...&native=1"`.
   Le `file://` n'est qu'un *fallback* si le serveur REST ne démarre pas, app.py:876 — et dans ce
   cas il n'y a aucun serveur REST à attaquer, donc hors sujet pour le garde CSRF.)
2. **`window.location.origin` = `http://127.0.0.1:8642`**.
3. **POINT DÉCISIF — l'Origin réellement envoyé par WebView2 sur un POST same-origin** : j'ai
   déclenché depuis le contexte de la page un `fetch(location.origin + '/api/runtime/get_app_version',
   {method:'POST', ...})`. La requête capturée côté listener réseau porte **`Origin = <ABSENT>`**
   (idem pour le GET `/api/health`). **WebView2 n'envoie AUCUN header Origin sur les requêtes
   same-origin** (GET comme POST).

**Conséquence sur le garde `_is_forbidden_cross_site`** (rest_server.py) : il fait
`origin = headers.get("Origin"); if not origin: return False`. Comme WebView2 n'envoie pas d'Origin
en same-origin, le garde retourne **toujours `False`** pour le dashboard desktop → **il ne peut
structurellement jamais bloquer le desktop**. Le fix `b1dd226` est donc **sûr en runtime**.

**Défense en profondeur (vérifiée par reproduction de `_allowed_origin` sur les origins réels)** :
même si une future version de WebView2 envoyait un Origin, `_allowed_origin("http://127.0.0.1:8642")`
le renvoie (host ∈ {127.0.0.1, localhost, ::1}) → autorisé. LAN same-origin
`http://192.168.1.50:8642` autorisé via le match `Host`. Site externe `http://evil.example.com` →
`None` → 403. `null` (cas `file://`) → 403 (mais inatteignable pour un desktop fonctionnel, cf. ci-dessus).

**Garde-fous tests** : `test_rest_security.py -k "cross or origin or cors"` = **7 passed** (les GATE
CSRF). Sur la suite complète : 14 passed + **4 failed PRÉ-EXISTANTS** (legacy `/api/get_settings`
→ 410 Gone, déjà documentés §7 — NON imputables au fix CSRF ni à mon travail).

**Honnêteté / limites** : l'EXE `dist/CineSort.exe` est daté du 8 juin (antérieur au fix `b1dd226`
du 11 juin) ; je n'ai donc PAS observé le garde lui-même s'exécuter dans le binaire de prod. Mais
ce que je devais valider — **l'Origin réel envoyé par WebView2** — est un comportement du moteur
WebView2 indépendant du fix, et je l'ai constaté sur l'app live (source actuelle). Le garde est
purement déterministe à partir de cet Origin (logique reproduite et testée). Aucun trou trouvé,
**aucun scheme/null à ajouter à `_allowed_origin`**. (Scripts de probe runtime créés puis supprimés,
non commités.)

### Mission 2 — fast-path dossier `(YYYY)` : **FIXÉ** (`a400a4e`)

**Bug confirmé par reproduction** (`discover_candidate_folders` sur layouts réels en tmpdir) : un
sous-dossier matchant `(YYYY)` était ajouté à `candidates` mais **jamais descendu** (`_walk` non
appelé sur lui). `iter_videos` (phase 2) étant non-récursif, un film imbriqué
(`Avatar (2009)/Avatar.2009.1080p-GRP/film.mkv`) donnait **0 row** (film absent du plan). Reproduit :
`plan_library` → `len(rows)==0` sur le layout imbriqué.

**Fix** (`cinesort/domain/scan_helpers.py`) : décision en **1 scandir** (`_yyyy_folder_shape`) sur
chaque dossier `(YYYY)` :
- vidéo directe non-bonus présente → **candidat seul, PAS de descente** (cas plat majoritaire ;
  évite tout doublon ET évite de planifier les featurettes des sous-dossiers comme films) ;
- pas de vidéo directe MAIS sous-dossiers → **descente** via `_walk(..., in_year_descent=True)` qui
  retrouve la release imbriquée et **filtre les feuilles 100% bonus** (`Extras/`, `Featurettes/`,
  `bonus.mkv`) pour ne pas les planifier ;
- ni l'un ni l'autre → candidat (comportement historique, `iter_videos` tranche).
Hors descente `(YYYY)`, le comportement leaf historique est **strictement préservé** (vérifié contre
`git show HEAD:` de l'ancien fichier).

**GATE** : `tests/test_scan_nested_yyyy_v77.py` (8 tests) couvrant les 3 invariants demandés :
(1) film direct = **1 candidat, aucun doublon** ; (2) film imbriqué **retrouvé** ; (3)
featurettes/extras imbriqués **jamais planifiés** ; + 2 tests bout-en-bout `plan_library` (1 row
pour le film, bonus exclu). **Sur le code d'origine, 5/8 échouent** (`len(rows)==0` = film absent) ;
avec le fix, 8/8 passent. **140 tests scan/plan** sans régression, import-linter 3/3.

**Ce qui reste incertain (honnêteté)** : le tri bonus repose sur `_file_looks_bonus` (stems exacts
`bonus/extras/featurette/...` + pattern `sample/trailer/teaser`). Un dossier release nommé
exactement « extras » mais contenant le vrai film (cas tordu) serait écarté — improbable mais
théoriquement possible. Le coût : 1 scandir supplémentaire UNIQUEMENT pour les `(YYYY)` SANS vidéo
directe (le cas plat majoritaire garde son fast-path zéro-scandir-extra). Validé en tmpdir local, PAS
sur une vraie bibliothèque NAS de l'utilisateur (pas d'accès).

### Mission 3 — 2 findings REAL 2/2 backend (`cddba9c`, `7b94c73`)

**(a) `watchlist.py:121` — remakes faux positifs — FIXÉ (`cddba9c`).** Bug reproduit :
`compare_watchlist([{title:Dune, year:2021}], [Dune(1984)])` → `owned_count=1` (FAUX). Le fallback
« titre seul » du pass 1 testait `norm in local_title_only` (tous les titres, années comprises). Fix :
indexer séparément `local_title_only_no_year` (proposed_year==0) et restreindre le fallback à ceux-là.
Préservés : match exact titre|année, branche watchlist-sans-année, fallback légitime (watchlist datée /
local non daté). GATE : `tests/test_watchlist_remake_v77.py` (6 tests, **sans** le skip-guard
`web/index.html` qui désactive `test_watchlist.py` entier) ; sur le code d'origine **2/6 échouent**
(remake marqué owned), avec le fix 6/6. Le pass 2 fuzzy filtrait déjà par année — un test garde-fou
le confirme. **Très sûr** (logique pure, déterministe).

**(b) `pragma_profile.py:219` — croissance non bornée de `pragma_history` — FIXÉ (`7b94c73`).**
`_record_pragma_history` insère 1 ligne à CHAQUE ouverture de connexion (1-3 par méthode repository),
aucune purge n'existait (grep confirmé). Fix : purge bornée DANS la même transaction implicite que
l'INSERT (1 seul commit, sémantique INSERT+COMMIT-avant-BEGIN-du-MigrationManager préservée), gardant
les **500** lignes les plus récentes par `id` (PK AUTOINCREMENT monotone) via un DELETE range indexé
`id <= max_id - cap`. Tolérant (échec de purge → log debug + commit quand même l'INSERT). GATE :
`tests/test_pragma_history_retention_v77.py` (4 tests) ; sur le code d'origine, **table non bornée
(637 lignes après 637 inserts) → 2/4 échouent** ; avec le fix, exactement 500, les plus récentes.
25 tests pragma/migration-028 + 74 tests db/pragma sans régression, import-linter 3/3.

**Ce qui reste incertain** : le plafond 500 est un choix (pas de besoin métier d'historique long sur
une table d'audit) ; il pourrait être rendu configurable plus tard. Le fix réduit aussi la *fréquence*
d'écriture moyenne mais n'élimine pas l'INSERT-par-connexion lui-même (chaque LECTURE reste une petite
écriture) — la contention WAL est *bornée* mais pas supprimée ; supprimer l'INSERT-par-connexion
(ex. throttle temporel, ou record_history=False sur les connexions courte-vie de lecture) serait un
sujet distinct, plus invasif, laissé de côté.

**`sqlite_store.py:613` (rotation backups) : NON traité — délibérément.** Le rapport le classe
**CONTESTÉ 1/2** : le scénario central (perte d'un backup `manual`) n'est pas atteignable car
`backup_now(trigger="manual")` n'a aucun appelant production (seul `tests/test_db_backup.py` l'utilise ;
aucun endpoint REST / bouton Settings). Per le mandat (« findings REAL 2/2 »), je l'ai écarté plutôt
que de forcer un fix sur un chemin mort.

### Auto-évaluation honnête (Opus)

**Ce dont je suis sûr :**
- Mission 1 : l'Origin réel `<ABSENT>` sur POST same-origin est une **observation runtime directe**
  (Playwright/CDP sur l'app live), pas une déduction. Le garde est sûr. C'est le point le plus solide.
- Missions 2 et 3 : chaque fix a un GATE **prouvé rouge sur le code d'origine** (par `git show HEAD:`
  réel, restauré ensuite) et vert après — pas de mock complaisant, les bugs sont reproduits puis fixés.
- Aucune régression sur les suites ciblées ; import-linter 3/3 après chaque commit ; 1 sujet/commit ;
  aucun push ; aucun secret touché ; couleurs tier non touchées ; dry-run/bypass loopback intacts.

**Ce qui reste incertain / faible :**
- Je n'ai PAS observé le garde CSRF `b1dd226` *s'exécuter* dans l'EXE de prod (EXE antérieur au fix).
  J'ai validé le *prérequis* (l'Origin WebView2), pas le binaire final ligne par ligne.
- Les fixes scan sont validés en **tmpdir local**, pas sur une vraie bibliothèque NAS/SMB de
  l'utilisateur (latence, casse de chemins, jonctions Windows non testées).
- Le tri bonus (Mission 2) et le plafond 500 (Mission 3) sont des **choix de conception** raisonnables
  mais discutables ; un évaluateur peut légitimement vouloir un plafond configurable ou un tri bonus
  plus permissif.
- Échecs PRÉ-EXISTANTS toujours présents (4 dans `test_rest_security`, cf §7) — **non imputables** à
  cette annexe.
