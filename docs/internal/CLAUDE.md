# CLAUDE.md — Instructions pour Claude Code

Ce fichier est le contexte projet pour les sessions Claude (CLI, GitHub Action, IDE).
L'historique complet des sessions passees est dans [CLAUDE_HISTORY.md](CLAUDE_HISTORY.md).

---

## Instructions

### Langue et style
- **Reponds en francais** sauf si le code est en anglais.
- Apres chaque lot de modifications, rapporte : ce qui a change, pourquoi, fichiers touches, tests lances, ce qui reste.
- Prefere les refactors incrementaux. Preserve le comportement existant sauf demande explicite.
- Pas de travail GitHub/CI/release sauf demande.

### MCP servers (utilisation proactive, sans attendre la demande)
- **context7** : doc a jour d'un framework ou lib avant de coder (pywebview, requests, Playwright, Ruff, PyInstaller).
- **memory** : stocke et recupere les decisions d'architecture et le contexte entre sessions.
- **sequential-thinking** : raisonnement complexe (debug, refactoring, design d'archi).
- **filesystem** : lecture/ecriture de fichiers dans le workspace.
- **playwright** : teste et observe l'interface UI dans un vrai navigateur.

### Securite (titre des films)
**Ne JAMAIS modifier le titre des films au-dela du renommage configure.** Les noms doivent rester syncro avec les torrents pour permettre le seed. Toute modification de naming doit etre opt-in via les settings et reversible.

---

## Etat actuel du projet (4 juin 2026)

### Version
- **v1.5.2-beta** (publique). Iteration beta consolidant la cloture de la roadmap initiale 6 vagues (M / N / O / P / Q / R) livree en juin 2026. Build EXE stable a 53.7 MB. Roadmap : v1.0 stable apres retours beta + Vague S+ (Linux port, B8 cleanup, 8 methodes orphelines UI), puis v1.1 features, v2.0 port Linux/Mac.

> Note : depuis le 17 mai 2026, plusieurs itérations beta (v1.1.x, v1.2.0-beta, v1.5.x-beta) ont consolidé l'audit C19 — alignement documentaire (README/architecture/SECURITY), refactor architectural (#83, #84), et roadmap 6 vagues (juin 2026). Aucune regression fonctionnelle, bundle EXE stabilise a 53.7 MB.

### Cycle adversarial en cours (3-4 juin 2026)
- **Branche** : `fix/v150-batch-bugs` (152 commits ahead vs origin, jamais pousses)
- **Etat** : 30 fichiers modifies en working tree, 543 commits sur 30 derniers jours
- **Vagues** : M / N / O / P / Q / **R completes** (tags `vague-r-complete`, `vague-r-hotfix1/2/3-full`)
- **Hotfix cycles** : 5 rounds adversarial bug hunts (R1=10crit, R2=5crit, R3=3, R4=1crit+17high, audit=0crit+16high) + 4 hotfixes precedents (post-fix rates 79%/93%/100%/100%) + hotfix6 (92% postfix, 1 revert auto)
- **Hotfix7 EN COURS** (worktree `w4yqqdf25`) : BugHunt R6 sur 10 angles + sequence corrigee. Tests biblio virtuelle: 11 bugs identifies -> 3 reels confirmes, 8 false positives.
- **Tag le plus recent** : `verify-fix-retest-complete` (2026-06-04)
- **Mega-hotfix** : tag `mega-hotfix` (2026-06-04) consolide les fixes B01-B05 du verify-cycle
- **Worktrees actifs** : 2 (CineSort principal sur fix/v150-batch-bugs + CineSort-B4 sur main)

### Architecture en couches (verrouillee par import-linter en CI)

```
ui/      <- (anti-corruption layer cote desktop + web)
  api/   <- 6 Facades par bounded context (run/settings/quality/integrations/library/runtime)
           + 47 modules *_support.py orchestrant les use-cases
    ^
    | (depend de)
    v
app/     <- Orchestration (apply_core, plan_support, jellyfin_sync, etc.) - 35 modules
  ^
  | (depend de)
  v
domain/  <- Logique metier pure (scoring, parsing, perceptual, naming) - 32 modules
  ^
  | (depend de)
  v
infra/   <- I/O (SQLite + 11 Repositories, TMDb/Jellyfin/Plex/Radarr clients, REST server)
```

**Contracts d'architecture** (`.importlinter`) :
1. `domain` ne peut PAS importer `app`, `infra`, `ui` (domain_pure)
2. `infra` ne peut PAS importer `app`, `ui` (infra_bounded)
3. `app` ne peut PAS importer `ui` (app_bounded)

Le cycle historique `domain -> app` a ete brise en mai 2026 (issue #83, phases A1-A8). Toute regression est bloquee par `lint-imports` en CI (job `Architecture contracts` dans `.github/workflows/ci.yml`).

**Modules recents centralisateurs** (vagues M-R, juin 2026) :
- `domain/path_utils.py` (VQ-1) : feuille du graphe, casse cycle core->duplicate_support->naming->core, expose `norm_win_path`/`_norm_win_path`/`windows_safe`
- `domain/codec_ranks.py` : centralise `AUDIO_CODEC_RANK_PATTERNS` (substring+label) + `AUDIO_CODEC_RANK` (dict exact) + `format_audio_channels` (VN-F.1)
- `domain/tiers_helpers.py` (Vague M / SCORE-02) : `TIER_ORDER_BEST_FIRST=[Platinum,Gold,Silver,Bronze,Reject]`, defaults 70/66/55/40 (calibration v1.5.7 853 films), AUCUNE couleur hex
- `domain/probe_models.py` : constantes `PROBE_QUALITY_FULL/PARTIAL/FAILED` + helpers (BUG-018 hotfix1)
- `infra/db/pragma_profile.py` (VO-A) : 4 profils SQLite (local_ssd/local_hdd/nas_smb/nas_smb_slow) + detection auto Windows
- `ui/api/_run_state.py` (ARCH-08 / M-07) : `RunState` extraite de cinesort_api.py (-165 LOC), thread-safe, `MAX_RUN_LOG_ITEMS=5000`

### Patterns architecturaux

- **Repository pattern (infra/db/repositories/)** : chaque domaine SQL a son repository — 11 repos (`anomaly`, `apply`, `decisions`, `field_locks`, `film_modal`, `perceptual`, `probe`, `quality`, `run`, `scan` + `_base`). `SQLiteStore` les instancie et expose `store.probe`, `store.anomaly`, etc. Le pattern coexiste encore avec les `_XxxMixin` legacy (thin wrappers de delegation) pour preserver `store.upsert_probe()`. Future : phase B8 supprimera l'heritage MRO une fois valide en prod.
- **Strangler Fig / Facade pattern (ui/api/facades/)** : **6 facades** (`run`, `settings`, `quality`, `integrations`, `library`, `runtime`) groupent ~166 methodes publiques sur `CineSortApi` via `_BaseFacade` composition wrapper. Les anciennes methodes directes `api.X(...)` sont marquees `_X_impl` (deprecated). Repartition methodes: Run 36, Settings 20, Quality 40, Integrations 15, Library 23, Runtime 32.
- **Module-style imports pour tests mockes** : quand un test fait `patch("cinesort.infra.plex_client.PlexClient")`, le module qui appelle PlexClient doit l'importer en `import ... as _mod` pas en `from ... import`. Pattern documente dans `cinesort/ui/api/apply_support.py`, `cinesort_api.py`, `perceptual_support.py`.

### Stack technique

- **Python 3.13** + pywebview >= 5.0 (UI desktop) + http.server stdlib (REST server)
- **SQLite WAL** (31 migrations, schema v31 — derniere: `031_tri_etat_decisions.sql`)
- **Dependances clefs** : `requests`, `rapidfuzz` (matching), `segno` (QR), `onnxruntime` + `numpy` (LPIPS perceptuel)
- **Probe** : ffprobe + mediainfo (binaires externes)
- **Tests** : pytest (>= 9.0.3) + hypothesis + Playwright (E2E dashboard) — **441 fichiers test_*.py** (396 racine + 45 sous-dossiers), 35 tests v77, top modules: phase (54), perceptual (15), apply (13), quality (12), tmdb (10)
- **Qualite** : ruff (lint + format), import-linter, pre-commit, codecov (coverage), bandit, mypy
- **Build** : PyInstaller (~54 MB onefile EXE Windows — **`dist/CineSort.exe` est le livrable final**, `build/CineSort/` est intermediaire PyInstaller a ignorer)

### Conventions de code

- **Imports** : top-level uniquement, sauf cycle inevitable (3 cas restants dans `cinesort/app/cleanup.py` -> `apply_core.py`).
- **Erreurs API** : utiliser `_err_response()` (`cinesort/ui/api/_responses.py`), categories `validation|state|resource|permission|config|runtime`.
- **Logs** : `logger = logging.getLogger(__name__)` + scrubber installe globalement (8 patterns secrets).
- **Tests** : `unittest` + `pytest` discovery. Pas de mock de DB (integration tests sur vraie SQLite).
- **Pas de docstrings multi-paragraphes** dans le code. Pas de comments WHAT (le code se lit), seulement les WHY non-evidents.

---

## Memoires user INVIOLABLES (rappel)

Ces regles sont issues des memoires user persistantes et doivent etre respectees a toute iteration :

1. **Reponses en francais** (sauf code en anglais).
2. **Couleurs tier hex INVARIANTES** : Platinum `#E5E4E2`, Gold `#FFD700`, Silver `#C0C0C0`, Bronze `#CD7F32`. Definies UNIQUEMENT dans `web/shared/tokens.css`. Aucune duplication dans `domain/` (qui ne contient que l'ordre et les seuils).
3. **Backward compat ABSOLUE** : toute migration/refactor doit preserver les anciennes API publiques (Strangler Fig). Exemple : `031_tri_etat_decisions.sql` coexiste avec la persistance JSON `validation.json` via helper `to_legacy_ok_bool`.
4. **`perceptual_reports` != `quality_reports`** : tables et modules distincts, ne jamais merger. `domain/perceptual/` (24 fichiers) est independant de `domain/quality_score.py`.
5. **DPAPI** : tokens d'auth jamais stockes en clair. Utiliser le wrapper Windows DPAPI pour chiffrer au repos.
6. **Architecture verrouillee par import-linter** : 3 contracts (`domain_pure`, `infra_bounded`, `app_bounded`). Toute regression bloque la CI.
7. **Actions dangereuses UI** : suppression/marquage/reset doit demander confirmation supplementaire, modale avec liste elements + consequence + delai 3s si > 50 elements.
8. **Subprocess direct > wrappers Python** pour binaires externes (ffprobe, mediainfo).
9. **Multi-agents en parallele** dans worktrees isoles pour chantiers >= 2 taches independantes (pas de sequentiel).
10. **SQLite migrations** : ordre `CREATE TABLE -> CREATE INDEX`, `IF NOT EXISTS` partout, pas d'`ALTER`, idempotentes, tester avec base PRE-EXISTANTE (pas uniquement fraiche).
11. **Bundle size** : pas un frein. Tout inclure dans le bundle plutot que DL au 1er usage. Qualite > optimisation taille.
12. **MAJ CLAUDE.md + BILAN_PHASES.md obligatoire** en fin de session/phase.

---

## API REST (architecture dispatcher)

Dispatcher unique : `cinesort/infra/rest_server.py` (1193 lignes, HTTP stdlib, pas de Flask/FastAPI).

### Format d'URL canonique
- **Actif** : `POST /api/<facade>/<methode>` avec body JSON (params kwargs)
  - Exemple : `POST /api/run/start_plan` (PAS `POST /api/start_plan`)
  - 6 facades : `run`, `settings`, `quality`, `integrations`, `library`, `runtime`
- **Legacy DESACTIVE** depuis 2026-05 (P0 #233) : `POST /api/<methode>` direct renvoie **410 Gone**, sauf si `CINESORT_REST_LEGACY_PASS1_ENABLED=1`.

### Endpoints non-dispatcher
- `GET /api/health` (+`active_run_id`, `last_event_ts`)
- `GET /api/spec` (OpenAPI 3.0.3 auto-genere)
- `GET /dashboard/*`, `/shared/*`, `/locales/*`

### Securite
- Auth Bearer token via `hmac.compare_digest` (rest_server.py:435)
- Rate-limit : 5 echecs / 60s / IP + global 4x
- Bind `127.0.0.1` par defaut
- `_MAX_BODY_SIZE = 16 MB`
- Convention `http_status` opt-in (Phase 11 v7.8.0) dans return dict pour codes metier 4xx/5xx sans casser `ok=true`.

---

## Sessions recentes

### 14 juin 2026 — Vagues R6 + R7 + audit patterns (44 fixes) ✅

Session Opus 4.8 sur `loop/correction-2026-06` (jamais pousse), declenchee par
analyse de captures de l'app reelle puis "on corrige tout" / "fais tout le reste".

**Vague R6 (13 commits, c8c123c..76b0043)** : R6-G fausse alerte TMDb (lit
`_has_tmdb_api_key`) ; R6-F page Qualite = distribution dernier run (965 films,
fini "tout Bronze" qui lisait le perceptuel cross-run) ; R6-E fonds opaques
(`.modal-card`/`.card` sans background, drawer biblio `--surface-1`, dropdown
`color-scheme:dark`) ; R6-A doublons groupes par IDENTITE titre+annee toutes
racines + badge scope + exclusion tv_episode (avant : groupes QUE si collision
de destination -> cross-racine rates) ; R6-D comparateur (onglets Frames/Audio
debloques : flag `LoadedByPair` pose avant querySelector -> fix flag apres succes
+ garde `LoadingByPair` ; nom "?" car `_filename_from_row` lisait `folder` au lieu
de `source_folder` ; taille octets bruts) ; R6-C/B cache doublons inter-navigation
(`_groupsCache` par runId) ; R6-I (year_missing mappe, confidence_avg, Etape 2
review_queue/conflicts) ; Comparer biblio en readOnly ; R6-H jaquettes (enrich
renvoie `ids:{row_id:tmdb_id}` + client patche r.tmdb_id ; onerror sur posters).

**Audit "patterns R6" (workflow 56 agents, verif adversariale)** : 33 bugs
confirmes -> 18 synthetises (4 HIGH / 9 MED / 5 LOW). Rapport :
[AUDIT_PATTERNS_R6_2026-06-14.md](./AUDIT_PATTERNS_R6_2026-06-14.md). Familles
recurrentes : front lit une cle que le back niche/ne fournit pas ; agregation
cross-run ; CSS transparent ; secret masque lu comme valeur ; feedback trompeur ;
**write-only jamais consomme** ; rendu/onerror posters.

**Vague R7 (18 commits, 33e735d..d9ab69d)** : 1 sujet=1 commit, GATE
fail-before/pass-after chacun. HIGH : R7-1 KPI QIJ sous `summary.*` ; R7-2
film-detail lit `probe.detected.*` ; R7-3 override TMDb manuel effectif (overlay
biblio+fiche+apply, table reste source) ; R7-4 "Marquer pour suppression"
consomme par l'apply (bucket `_user_marked_for_deletion/`, miroir isole des
losers). MED : R7-5 summary KPI dernier run ; R7-6 Inspecteur Historique
(films+doublons) ; R7-7 progression scan (`run_info` dans get_dashboard) ; R7-8
refresh poster force le proxy (cache disque + cache-bust) ; R7-9 CSS drawers/
selects (complement R6-E) ; R7-10 reveal token REST (localhost-only) ; R7-11
recompute compte les `{ok:False}` ; R7-12 unmark/clear override cables
(impl+facade+endpoints+UI). LOW : R7-13 playlist warnings ; R7-14 recap Apply
(result.renames+moves) ; R7-15 trend perceptuel COUNT(DISTINCT row_id) ; R7-16
onerror vignettes ; R7-17 message cle TMDb absente fiche film.

**Verifs** : 166 GATEs+regression verts, import-linter 3/3, py_compile/node OK,
EXE rebuild. ~35 fichiers test v77 neufs cette session.

### 11 juin 2026 (suite) — Verification totale + vague R4 (14 fixes) ✅

**Verification totale** demandee par l'utilisateur : workflow 65 agents (128 findings, 21 challenges,
20 confirmes en double-refutation, 0 refute) + suite complete (5642 passed, 22 echecs TOUS
pre-existants — 8 nouveaux suspects prouves pre-existants via worktree temporaire au commit pre-vague).
Elle a attrape 4 vrais defauts DANS les fixes R1-R3 -> **vague R4, 14 commits** (annexe R4 du handoff) :
- **P1 `90e21e4`** : perceptual_workers refait a la racine — cle UI = canonique (l'UI POST l'objet
  settings ENTIER, echo du GET : le fallback alias R3c etait mort, GATE complaisant). Memoire creee :
  feedback_cinesort_settings_full_payload.
- **P2 `d40f57c`** : _RELEASE_GROUP_RE tiret COLLE (9 mutilations R1a reparees + 1 pre-existante,
  differentiel corpus 0 divergence scene).
- **P3 `b336cc9`+`05cf075`+`1a2f9c6`(+`37e76c8` fix test)** : langues hors _LANG_MAP conservees,
  tags de piste exclus (forced/sdh/cc/commentary/mul/multi/und/qaa-qtz), build embarques bruts.
- **P4 `72ab67f`+`638e192`** : replan multi-root — _resolve_scan_root_for_replan (contient le film,
  plus profond gagne, candidats normalises, PlanRow.source_root prioritaire).
- **P5-P14** : drawer Qualite (sources/decades/Autre `7ba6f43`, genres morts retires `48cde2e`,
  period_days=0 `5ebd35e`) ; purge secrets historiques runs.config_json au boot `552bf69` ;
  4 round-trips settings `a0e4714` (collection_folder_name, lowercase_extensions au GET, split ';',
  file_extensions->video_exts) ; badge 0=configure `5d5b3c6`.

**Revue adversaire R4** (9 agents + reprise post-quota, union 53+34 findings) : tout juge (inline,
quota agents tombe 2x — reset 16/06 21h ; relance possible resumeFromRunId wf_7e1cf1c1-092).
Verifs : suite complete post-R4 5676 passed / 22 echecs = baseline exacte ; 293+52 tests cibles
verts ; import-linter 3/3 ; node --check x3. Residuels documentes dans l'annexe R4 du handoff
(settings fantomes, drop sous-titres externes amont, HDTV≡Autre, router query params, artefacts dist/).

### 11 juin 2026 — Audit de verification + vague de correction R1/R2/R3 (13 fixes) ✅

Verification multi-agents (lecture seule, double-refutation) des 35 fixes Vagues 1-6 + 3 fixes Opus
(`AUDIT_EVALUATION_HANDOFF_2026-06-11.md`). Conclusions : les 3 fixes Opus sont RESOLU ; **2
regressions** introduites par les Vagues 1-6 ; **3 fixes PARTIEL** (GATE complaisant/absent) ;
plusieurs **gaps PAS-CORRIGES** reels. Resultats bruts dans `_verif_audit_2026-06-11.json`.

**13 commits R1/R2/R3** sur `loop/correction-2026-06` (jamais pousses), 1 sujet/commit, GATE
rouge-avant/vert-apres prouve par `git show HEAD:` reel pour chacun :
- **R1 (2 regressions)** : scene_parser garde release-group sur `_NOISE_RE` complet (`50acdaf`) ;
  secrets NON persistes en clair dans `runs.config_json` via `_scrub_secrets_for_persist` (`63517d7`).
- **R2 (.ts + 3 PARTIEL durcis)** : `.ts` ne force plus `source_hint=cam` (`dbaa07c`) ; vrais GATE
  jellyfin date map / quality scope / film events (`760f404`).
- **R3 (gaps reels)** : perceptual_auto_on_quality lit le dict plat (`c7c0627`) ; 5 filtres drawer
  avance (codec/resolution/source/langues/sous-titres) (`d282bf3`) ; perceptual_workers_count UI
  persiste (`191b916`) ; garde 24h sur undo_selected_rows (`5a7d975`) ; slot-guard sur chemins undo
  reels (`f4bc0fe`) ; reconciliation exige `expected_ops` avant COMPLETED (`90b7961`) ; row cache v2
  compare le `kind` (`90e0464`) ; replan folder_name idempotent via `library_root` (`d4a4ded`) ;
  circuit breaker probe alimente en backend auto, evite le hang ~41h NAS down (`bc653b5`).

**Verifs finales** : 168 tests (modules touches + tous les GATE) passed, 0 regression ; import-linter
**3 contrats KEPT** ; couleurs tier/DPAPI/dry-run/bypass loopback intacts ; aucun push. Modele Fable 5.
8 fichiers test v77 neufs cette vague (apply_batches_reconciliation, row_cache_kind_guard,
replan_idempotent_folder_name, probe_breaker_auto_wiring, perceptual_workers_persist, undo_24h,
undo_apply_slot_guard, config_secrets_scrub).

### 10-11 juin 2026 — Audit relecture integrale + backlog de correction (4 vagues) ✅

Relecture multi-agents de tout le code (~120k lignes, workflow `wf_984bef0d-63a`, ~510 agents,
panel de double-refutation). **314 findings uniques** (5 CRITICAL, ~140 HIGH), 106 REAL 2/2.
Rapport complet : [AUDIT_RELECTURE_2026-06-10.md](./AUDIT_RELECTURE_2026-06-10.md).

**20 commits de correction sur branche `loop/correction-2026-06`** (jamais pousses), chacun avec
GATE et import-linter vert :
- **Vague 1 — perte de donnees (3)** : TTL quarantaine sur date d'entree (manifest) pas st_mtime
  (`7089cab`) ; journal write-ahead apply par-row preserve (`9d89200`) ; rollback revert aussi
  QUARANTINE_* (`e7346ee`).
- **Vague 2 — securite (6)** : garde CSRF same-site + CORS sans wildcard (`b1dd226`) ; OMDb HTTPS
  (`5dc70ea`) ; scrubber args non-str + re-sync apres basicConfig (`e20d2c0`) ; whitelist binaire
  probe dans _resolve_tool_path (`8a387f2`) ; SHA256 archives epinglable par env var (`9ef5457`).
- **Vague 3 — secrets masques ~12 chemins (4)** : hydratation scan ignore le masque (`f11bf2a`,
  couvre accueil+watcher) ; helper `_internal_settings` pour 7 rapports Jellyfin/Plex/Radarr/SMTP
  (`1eb1fb0`) ; rescan TMDb (`74171f0`) ; restart REST token+host+cors (`a0a8701`).
- **Vague 4 — contrats JS vivants (3)** : doublons group_key aligne backend (`e347684`, evitait la
  perte des decisions Garder A/B) ; accueil detecte erreurs metier res.data.ok (`b4c6fdb`) ;
  traitement auto-save unmount detache de l'abort (`ba10800`).

**Reste a faire** (documente dans le rapport) : findings JS necessitant validation runtime (app live
/ Playwright) — progression accueil, drawer options, processing.js, vues mortes status/qij/quality ;
+ les 37 findings CONTESTES (bug source reel mais chemin mort) ; + angles non couverts par l'audit
(CI/packaging/locales/tests). 2 echecs de tests PRE-EXISTANTS hors perimetre a traiter
(test_apply_op_labels, RecordApplyOpTests + 4 legacy-410 dans test_rest_security).

### 3-4 juin 2026 — Vague R complete + cycle hotfix6/7 (BugHunt R6) 🟡 EN COURS

Cycle adversarial intensif post-Vague Q, 30 tags poses entre le 02 et le 04 juin :

**Vague R cloturee** (`vague-r-complete`, `vague-r-hotfix1/2/3-full`) puis cycle `verify-cycle` sur bugs B01-B05 (`mega-hotfix`, `verify-fix-retest-complete`).

**Recap rounds adversariaux** :
- R1 : 10 critiques identifies
- R2 : 5 critiques (convergence)
- R3 : 3 / R4 : 1 critique + 17 high / Audit : 0 critique + 16 high
- 4 hotfixes precedents : post-fix rates 79% / 93% / 100% / 100%
- Hotfix6 : 92% postfix (11/12), 1 revert auto, retests 0/4 (sequence cassee)
- **Hotfix7 EN COURS** dans worktree `w4yqqdf25` : BugHunt R6 sur 10 angles + sequence corrigee

**Tests biblio virtuelle** : 11 bugs candidats -> 3 reels confirmes (8 false positives).

**Migrations 027-031 deployees** (Vagues L+O+P) :
- 027 : self_healing_023_v2 (re-applique IF NOT EXISTS pour ignored_alerts/film_marked_for_deletion/film_tmdb_overrides)
- 028 : pragma_history (audit bascules profil SQLite)
- 029 : apply_atomic_mode (rollback forward enum 5 valeurs)
- 030 : field_locks Jellyfin-style (lecon bug Jellyfin #15549)
- 031 : tri_etat_decisions (`accepted`/`rejected`/`deferred` avec CHECK, coexiste validation.json via `to_legacy_ok_bool`)

**Backlog** : 152 commits non pousses sur `fix/v150-batch-bugs`, 30 fichiers modifies en working tree.

### 2 juin 2026 — Bilan 5 vagues completes (M / N / O / P / Q) ✅

Recap synthetique de 5 vagues consecutives livrees en juin 2026. Detail complet dans
[BILAN_PHASES.md](./BILAN_PHASES.md).

**Resume** :
- **Vague M** : 9 items (cloture refactor #84) + 1 hotfix bundle EXE (2.33 GB -> 54 MB) + 8 quickwins
- **Vague N** : 17 items — Chromaprint audio, scoring unifie, WCAG AA, pause cooperative, apply_audit logger
- **Vague O** : 4 items — SQLite pragmas profils, scan parallel x2.5, waterfall UI, OpType StrEnum
- **Vague P** : 7 items — apply atomique, tier TRaSH hierarchique, field locks Jellyfin, tri-etat, optimistic concurrency, TRaSH YAML, tags providers brackets
- **Vague Q** : 3 items — path_utils, quarantaine TTL, check_path_length MAX_PATH

**Stats globales** :
- 40+ items livres, 31+ workflows GitHub Actions, 5 migrations SQL neuves (027-031)
- Bundle EXE : 59 MB (v166) -> 2.33 GB (regression torch) -> **54 MB stable** apres hotfix
- 25 tags git poses (`sprint-0-inventory` jusqu'a `vague-q-complete`)
- Methodologie : multi-agents en parallele dans worktrees isoles, revue adversaire iterative R1/R2 avant chaque tag de cloture

### 1 juin 2026 — M-03 cloture #84 etapes 2-4 (Vague M) ✅ partial

Item M-03-FINISH-REFACTOR-84 (Vague M, juin 2026). Strategie minimal-viable :
inventorier les lazy imports residuels au lieu de tout refactorer (risque trop eleve
pour gain modere).

**Constat** : apres Issue #83 (150 lazy imports convertis en mai 2026), il restait
**73 lazy imports** dans `cinesort/`, pas les 179 du re-budget pessimiste.

**Conversions safes appliquees (4)** :
- `cinesort/ui/api/settings_support.py` : `re`, `secrets` -> top-level
- `cinesort/ui/api/quality_simulator_support.py` : `re` -> top-level
- `cinesort/infra/db/migration_manager.py` : `Path` deja top-level, doublon supprime

**Reste 69 lazy imports volontaires** (deps optionnelles segno/onnxruntime/rapidfuzz,
platform-specific msvcrt/fcntl, cycles intentionnels documentes, `# noqa: PLC0415`).

**Garde-fou** : `tests/test_refactor_84_progress_v77.py` borne le count a 69
(`MAX_LAZY_IMPORTS=69`). Toute regression future declenchera le test.

**Status** : PARTIAL — Vague N+ peut reprendre le sujet pour les ~20 cas restants
convertibles (analyse fine par cas necessaire, hors budget M-03). Detail dans
`docs/internal/REFACTOR_PLAN_84.md` section "M-03".

### 21 mai 2026 — Audit complet 3 tiers (Tier 1 + Tier 2 + Tier 3 + docs) ✅

Audit exhaustif lance par l'utilisateur sur tout le repo (v1.2.0-beta).

**Tier 1 — Analyse statique (PR #339)** :
- ruff --select ALL + vulture sur tout `cinesort/`
- **22 occurrences fixees** sur 16 fichiers : F401, B904 x3 (perte chainage), B023 x4 (closure capture), B905 x6 (zip strict), RUF059 x5, vulture x2 (parametres vestigiaux dans `compare_duplicates` et `extract_aligned_frames`)
- 308 tests verts, 0 regression

**Tier 2 — Multi-agents par concern (PR #347 mergee)** :
- 6 sous-agents en parallele (run, quality+settings, library+integrations, cycles, UI↔backend, migrations SQLite)
- **2 HIGH** : race condition `set_active_profile` + `_tier_for` ordre invalide silencieux
- 9 MEDIUM fixes (categorisation `_err_response`, `tmdb_id` manquant dans library timeline, wrap `_get_movie_detail_cached`, etc.)
- 281 tests verts sur modules touches

**8 methodes backend orphelines identifiees** (sans entry UI) :
get_tmdb_posters, smart_playlists (CRUD), list_films_with_history, export_full_library, submit/delete_score_feedback. Issue tracker a creer pour roadmap UI.

**Findings deferes a auditer plus tard** :
- BLE001 blind-except (35) — pattern defensif systematique
- SLF001 private-member-access (538) — analyse archi
- S324 sha1 fingerprint (5) — annoter `usedforsecurity=False`
- RUF013/RUF012 (5) — typing bugs mineurs
- `audio_perceptual.py:221,277` rc ffmpeg ignore — risque silent failure quand `rc != 0` + stderr non-vide

**Detail complet** : `docs/internal/BILAN_AUDIT_TIERS.md`.

### 16 mai 2026 (soir) — #83 phases A6-A8 terminees, #85 phases B1-B7 ✅

**12 PRs mergees en cascade** apres la cassure du cycle (#193, #197, #202, #203) :

| PR | Phase | Module(s) | Lazy imports |
|----|-------|-----------|--------------|
| #194-#201 | B1-B7 | 7 Repositories migres (mixin -> Repository) | — |
| #204 | A8 | import-linter en CI (.importlinter + workflow) | — |
| #205 | A6 | 6 small files (quality_score, settings_support, ...) | 28 |
| #206 | A7a | perceptual_support.py | 13 |
| #207 | A7b | apply_core.py | 18 |
| #208 | A7c | plan_support.py | 36 |
| #209 | A7d-1 | cinesort_api.py (imports safes) | 34 |
| #211 | A7d-2 | cinesort_api.py (module-style mockes) | 21 |
| **Total A6+A7** | — | **11 fichiers** | **150** |

**Bilan** :
- 150 lazy imports convertis en top-level (sur ~165 au depart)
- 3 imports restent volontairement lazy dans `cleanup.py` (cycle `cleanup <-> apply_core` non lie a domain->app)
- Architecture verrouillee : `lint-imports` echoue en CI si quelqu'un ressuscite un cycle
- 7 Repositories pattern installes (composition au lieu d'heritage MRO)
- Tests : 4277 passent, 0 regression
- Issue #83 fermee, B8 reste (suppression des `_XxxMixin` apres validation prod)

**Security** :
- 9 alerts CodeQL B608 (SQL injection f-string) marquees false-positive : pattern recommande `f"... IN ({','.join('?' for _ in ids)})"` avec valeurs en parametres.
- 1 alert log-injection medium (rest_server.py:502) fixee dans PR #212 (sanitize CR/LF + cap 200 chars).

### 16 mai 2026 (matin) — Cleanup audit-bot + #94 + premieres etapes #83 ✅

9 PRs mergees, 5 issues fermees. Detail dans `CLAUDE_HISTORY.md`.

### 15 mai 2026 — Refactor god class CineSortApi (#84) + Logging structure API (#103) ✅

10 PRs Strangler Fig : 104 -> 50 methodes publiques sur CineSortApi via 5 facades. 198 sites `return {"ok": False}` migres vers `_err_response()`. Detail dans `CLAUDE_HISTORY.md`.

---

## Workflows GitHub Actions

| Workflow | Trigger | Role |
|----------|---------|------|
| `ci.yml` | push main + PR | lint (ruff) + format + **import-linter** + tests + coverage 80% + build EXE + smoke |
| `audit-module.yml` | cron daily 04h UTC + manual | Audit Claude par couche (rotation lun-ven) avec prompt dans `.github/audit-prompt.md` (46 categories, 6 personas) |
| `claude.yml` | @mention + cron weekly (lundi 04h UTC) | Claude Code Action sur PR/issue |
| `codeql.yml`, `bandit.yml`, `gitleaks.yml`, `pip-audit.yml`, `mypy.yml` | push + PR | Security + typing |
| `scorecard.yml` | weekly | OpenSSF Scorecard |
| `windows-ci.yml` | push + PR | CI Windows-specific |

---

## Claude AI Configuration

Configuration appliquee aux workflows GitHub Actions Claude (`claude.yml` et `audit-module.yml`) :

| Parametre | Valeur |
|-----------|--------|
| **Model** | `claude-opus-4-8` (Claude Opus 4.8 — latest) |
| **Thinking budget** | `--max-thinking-tokens 200000` (max) |
| **Effort** | `ultra` (qualite maximale, aucune limite de tokens) |
| **Daily run** | `.github/workflows/audit-module.yml` (cron `0 4 * * *`, audit quotidien par couche) |
| **Weekly run** | `.github/workflows/claude.yml` (cron `0 4 * * 1`, Claude Code Action) |

Notes :
- `--max-turns` (200 pour `claude.yml`, 1500 pour `audit-module.yml`) et timeouts (90min / 360min) preserves.
- Triggers, permissions, concurrency, `--allowedTools` et structure des steps inchanges.
- Historique modeles : Opus 4.5 / 4.6 / 4.7 → remplaces par Opus 4.8 (juin 2026).

*Last updated : 2026-06-14 (Vagues R6 + R7 + audit patterns : 44 fixes, 0 regression, 166 GATEs verts, import-linter 3/3, EXE rebuild ; cf AUDIT_PATTERNS_R6_2026-06-14.md).*

---

## Issues ouvertes (3)

| # | Sujet | Statut | Effort |
|---|-------|--------|--------|
| #14 | Umbrella audit | A laisser ouverte | — |
| #85 | Mixins SQLite -> Repositories (B8 cleanup) | Repositories faits (B1-B7), reste suppression mixins | 3-4h, 1 PR |
| (autres) | — | — | — |

---

## Verifications rapides

```bash
# Quality gate locale
check_project.bat                                                # Windows : compile + lint + format + tests + coverage
python -m pytest tests/ --ignore=tests/e2e --timeout=60 -q       # Tests rapides

# Architecture
lint-imports                                                     # 3 contracts (domain/infra/app boundaries)

# Build EXE
pyinstaller --noconfirm CineSort.spec                            # ~50 MB output dans dist/

# Lancement
python app.py                                                    # UI normale
python app.py --dev                                              # Console visible
python app.py --api                                              # REST seul, sans UI
```

---

## Documents utiles

- [README.md](../../README.md) — entree publique
- [CLAUDE_HISTORY.md](./CLAUDE_HISTORY.md) — historique complet des sessions
- [.github/audit-prompt.md](../../.github/audit-prompt.md) — prompt audit du matin (46 categories)
- [REFACTOR_PLAN_83.md](./REFACTOR_PLAN_83.md) — plan original casser cycle (acheve)
- [REFACTOR_PLAN_84.md](./REFACTOR_PLAN_84.md) — plan facades (acheve)
- [BILAN_CORRECTIONS.md](./BILAN_CORRECTIONS.md) — bilan audits successifs
- [AUDIT_RELECTURE_2026-06-10.md](./AUDIT_RELECTURE_2026-06-10.md) - relecture integrale du code 2026-06-10 (317 findings confirmes : 6 CRITICAL, 143 HIGH bruts), backlog de correction prioritaire
- [BILAN_PHASES.md](./BILAN_PHASES.md) — recap des grandes vagues (M / N / O / P / Q)
