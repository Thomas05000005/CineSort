# BASELINE R8 — CAPTURE DE RÉFÉRENCE DE L'ÉTAT CASSÉ (avant correction) — READ-ONLY

> **But** : figer le COMPORTEMENT RÉEL ACTUEL de CineSort (avec les ~82 bugs confirmés encore présents)
> comme RÉFÉRENCE mesurable. Chaque correctif R8 sera ACCEPTÉ seulement s'il fait basculer une observation
> de baseline « cassé → correct » **sans** faire régresser une autre observation. La baseline est à la fois
> **preuve de bug** ET **garde anti-régression**.
>
> **Read-only strict.** 0 correction / 0 commit / 0 push / pas de `git stash`. Branche `loop/correction-2026-06`,
> checkpoint code **`f493abdc`** (NON touché). Source des findings : `../AUDIT_HORIZONS_2026-06-15.md` (campagne
> 10 vagues, panel adversarial **0/28 faux-positifs**). Captures rejouables : `./captures/` (scripts + sorties figées).
> Instruments : `scripts/observe.py`, Playwright, serveur `python app.py --api` (UP sur 127.0.0.1:8642), fixtures
> tempfile / copies RO. **Jamais d'écriture sur la vraie bibliothèque ; aucun secret en clair.**

---

## 0. RÉCAP PAR FAMILLE (tête de rapport)

| Famille | Intitulé (ordre de correction R8) | Nb findings | dont perte-données / récup. mensongère | dont repro DÉJÀ figé |
|---|---|---|---|---|
| **F1** | Perte de données NON récupérable | 2 | 2 | 1 (`v9_coll_atomic`) |
| **F2** | Intégrité / invariants cassés / récupération mensongère | 28 | 10 | 6 (`v5_tv`, `c3e_cron`, `c3_concurrent`, `meta_roundtrip`, `v8_collmkdir`, +structural) |
| **F3** | Sécurité (surface résiduelle 314 / non-loopback) | 4 | 0 | 3 (`cap_live_sec_a11y` + `cap_residual`) |
| **F4** | Résultats FAUX silencieux | 11 | 0 | 8 (`h6` + `cap_false_results` 7) |
| **F5** | Features mortes / contrats désaccordés (4 seams + insights) + états UI | 33 | 0 | 30 (`cap_contracts_static` 16 + `cap_phantom_config` 14) |
| **F6** | Cosmétique / a11y / i18n / confort / hygiène | 7 | 0 | 3 (`cap_residual` + `cap_live_sec_a11y` I18N) |
| **—** | **TOTAL fix-targets** | **≈85** | **11** | **70 observations cassées figées (14 scripts) + 5 non-régression** |
| (annexe) | Latents / réfutés / intentionnels (NE PAS corriger) | 12 | — | — |

> **Lecture** : 11 findings touchent la perte de données ou un chemin de récupération mensonger (F1 + sous-clusters
> F2) → priorité absolue R8. **70 observations de l'état cassé sont figées et rejouables** (7 proofs historiques +
> 6 familles workflow + 1 résiduelle) ; restent **8 findings à instrumenter** (Playwright runtime / vrai ffmpeg /
> fixtures lourdes — §2.3). Les plus dangereuses sont déjà figées : collection à moitié appliquée + dedup empoisonné,
> sidecars TV orphelins, crons qui meurent sur sqlite, round-trip à perte, dossier saga orphelin.

---

## 1. REGISTRE R8 NUMÉROTÉ (inventaire figé, groupé par famille = §3 classement)

> Colonnes : **N°** · **ID** (clé dédup = `fichier:ligne ∪ cause-racine`) · **sév** · **fichier:ligne** ·
> **symptôme utilisateur** · **capture de référence** (artefact rejouable). Sévérité = celle adjudiquée en campagne.
> Les **clusters d'unification** (TV-apply, rollback, dedup-loser, migration, les 4 seams) sont signalés : R8 les
> traite en **un seul chantier de mise à parité**, pas bug par bug.

### ███ F1 — PERTE DE DONNÉES NON RÉCUPÉRABLE ███

| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-001 | **F-V8-COLL-ATOMIC** | 🔴 high | `apply_core.py:2112-2148` | `apply_collection_item` déplace les sidecars AVANT la vidéo ; si le move vidéo échoue (mkv verrouillé), sidecars déjà dans `sub_dir/`, vidéo bloquée en source = **collection à moitié appliquée**, 0 rollback. **Amplification** : le ledger `dedup_seen_ops` marque la vidéo « vue » → un retry SKIPPE la vidéo → **demi-application PERMANENTE / irrécupérable**. | `captures/v9_coll_atomic_repro.out.txt` ✅ figé (`half_applied=true, dedup_poisoned=true`) |
| R8-002 | **F-QTN-GOV** (V3 [0]) | 🟠 medium | `quarantine_ttl.py` ↔ buckets `run_dir/_review` (`%LOCALAPPDATA%/runs/`) | La TTL configurée (30 j) gouverne `cfg.root/_review`, mais l'apply écrit conflicts/sidecars/duplicates_identical/leftovers sous `run_dir/_review` → **4/5 buckets hors TTL**, purgés par la rétention-runs (`clean_old_runs keep_last=20` rmtree) → des originaux quarantinés peuvent disparaître **avant** revue utilisateur (lifecycle = rétention-runs, pas la TTL). | `captures/cap_qtn_governance` (à figer — mécanisme TTL sain prouvé par `c1_quarantine_ttl_fix`) |

**Note unification F1** : les deux concernent l'apply non-atomique / la gouvernance de quarantaine. R8 : rendre
`apply_collection_item` atomique intra-row (vidéo d'abord ou rollback compensatoire + **ne pas empoisonner le dedup
avant le move réussi**) ; faire gouverner les buckets `run_dir/_review` par la TTL configurée (ou documenter le lifecycle).

### ███ F2 — INTÉGRITÉ / INVARIANTS CASSÉS / RÉCUPÉRATION MENSONGÈRE ███

#### Cluster 2.A — `apply_tv_episode` : sous-système parallèle JAMAIS mis à parité avec le chemin film (1 chantier R8)
> Cause racine unique : copie parallèle d'`apply_single`/`apply_collection_item` qui n'a reçu ni les gardes ni les
> filets du chemin film. Grille de parité complète = `../AUDIT_HORIZONS_2026-06-15.md` (Vague 7, 13 gardes).

| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-003 | **F-V6-TV-MAXPATH** | 🔴 high | `apply_core.py:2222` | kill-switch MAX_PATH ne teste QUE `target_file` ; un sidecar long (`release+.fr.forced.sdh.srt`) dépasse 260 → OSError / move partiel (épisode déplacé, sidecar bloqué). Le film vérifie `_longest_inner`. | `captures/cap_tv_parity` |
| R8-004 | **F-V4B-TV1** | 🟠 medium | `apply_core.py:2253` | vidéo renommée `SxxExx - Titre.ext` mais sidecars déplacés avec `dst_side = target_dir / sidecar.name` → **nom source conservé → tous les .srt/.nfo/.jpg orphelins** (Jellyfin/Kodi/Plex ne les associent plus). | `captures/v5_tv_apply_repro.out.txt` ✅ figé (`B1_sidecars_orphelins=true`) |
| R8-005 | **F-V4B-TV2** | 🟠 medium | `apply_core.py:2241` | ops MOVE_FILE TV enregistrées **sans `src_sha1`/`src_size`** → `preverify_undo_operations` les classe `legacy_no_hash` → garde-fou « fichiers modifiés depuis l'apply » **INERTE pour tout le chemin TV**. | `captures/v5_tv_apply_repro.out.txt` ✅ figé (3 ops, `src_sha1=<absent>`) |
| R8-006 | **F-V5-TV3** | 🟠 medium | `apply_core.py:2232` | NOOP skip dès `target_file.exists()` **sans comparer le contenu** ni quarantaine → 2 épisodes distincts mappant la même cible : le 2ᵉ (différent) **silencieusement laissé en source**. Le film passe par `move_file_with_collision_policy`. | `captures/cap_tv_parity` |
| R8-007 | **F-V6-TV-SIDECOLL** | 🟠 medium | `apply_core.py:2253` | sidecar déplacé seulement `if not dst_side.exists()` → 2 épisodes à sidecar de nom collidant (poster.jpg générique) : le 2ᵉ **abandonné en silence** (ni move ni quarantaine ni log). | `captures/cap_tv_parity` |
| R8-008 | **F-V6-TV-MKDIR** | 🟠 medium | `apply_core.py:2239` | `target_dir.mkdir()` brut au lieu de `mkdir_counted` → `res.mkdirs` jamais incrémenté + **aucune op MKDIR journalisée** pour les dossiers Série/Saison → rollback ne les supprime pas. | `captures/cap_tv_parity` |
| R8-009 | **F-V7-TV-LEFTOVERS** | 🟡 low-med | `apply_core.py:2168-2266` | `apply_tv_episode` ne reçoit pas `leftovers_root` et ne nettoie ni les fichiers non-matchés (samples/.txt) ni le dossier source vidé → résidus laissés en source après apply TV. | `captures/cap_tv_parity` |
| R8-010 | **F-H3-02** | 🟡 low | `apply_core.py:2263` | `except (PermissionError, OSError): pass` avale l'échec de déplacement d'un sidecar (.srt verrouillé) → .mkv déplacé, .srt orphelin, run rapporte « succès » **sans WARN** (`res.moves += 1`). | `captures/cap_tv_parity` |
| R8-011 | **F-V6-UNDO-CASE** | 🟠 medium | `apply_support.py:442` | apply special-case le rename casse-seule (`_case_only_rename_with_rollback`) mais l'undo fait `if target_path.exists()` → sur Windows case-insensitive, l'undo de `Film`→`film` est classé CONFLIT (déplacé `_undo_conflicts`+FAILED) au lieu de restaurer. Asymétrie apply/undo. | `captures/cap_tv_parity` (structural) |

#### Cluster 2.B — Rollback / statut de batch op-level (récupération mensongère)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-012 | **F-V4B-RB1** | 🟠 medium | `apply_rollback.py:335-340` | après revert FS réussi, `rollback_forward` ne marque JAMAIS `apply_operations.undo_status` → batch reverti apparaît `pending_ops=total, undone_ops=0` = « jamais annulé, entièrement undoable » alors que le FS est déjà revenu. | `captures/cap_integrity_structural` |
| R8-013 | **F-V4B-RB2** | 🟠 medium | `apply_rollback.py:378-380` | process tué pendant le revert → `rollback_status` figé `IN_PROGRESS` à vie, FS à moitié reverti ; `reconcile_pending_batches` ne scanne que `status='PENDING'` (le batch est `FAILED`) → **aucun chemin de récupération**. | `captures/cap_integrity_structural` |
| R8-014 | **F-APPLY-DONE** (V3 [4]) | 🟠 medium | `apply_support.py:1565` | `close_apply_batch(status="DONE")` **codé en dur** malgré `result.errors>0` → apply partiellement échoué affiché « terminé ». | `captures/cap_integrity_structural` |
| R8-015 | **F-APPLY-FAILED** (V3 [5][7]) | 🟠 medium | `apply_support.py:2213` | batch atomique qui lève → `status='FAILED'` figé **avant** `rollback_forward` ; le verdict `ROLLBACK_PARTIAL/FAILED` ne va que dans la table annexe `apply_batch_modes.rollback_status` → impossible de savoir si le FS est restauré. | `captures/cap_integrity_structural` |
| R8-016 | **F-APPLY-ZOMBIE** (V3 [8]) | 🟡 low | `apply_batches_reconciliation.py:170` | batch zombie complet sans `expected_ops` → `"rolled_back"` (UPDATE statut seul, aucune action FS) → mislabel d'observabilité (intentionnel, batches legacy). | `captures/cap_residual.out.txt` ✅ figé |

#### Cluster 2.C — Dedup-loser (helpers greffés sans le pattern existant)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-017 | **F-V10-LOSER-ATOMIC** | 🟠 medium | `apply_core.py:1303,1320` | `move_duplicate_losers_to_user_decided` + `move_marked_for_deletion_to_bucket` appelés **avant la boucle row, HORS try/except** → un loser/marked verrouillé lève une exception non rattrapée → **avorte TOUT le batch** (winners + rows non traitées), travail partiel laissé. Une row normale est attrapée per-row. | `captures/cap_integrity_structural` (structural) |
| R8-018 | **F-V10-LOSER-COUNTER** | 🟠 medium | `apply_core.py:1042,1056,1077` | les helpers loser incrémentent `duplicates_identical_moved_count` (compteur des **byte-identiques**, lockstep avec `_deleted_count`) → **invariant `moved==deleted` cassé** + losers dans `_duplicates_user_decided` alors que l'UI pointe `_duplicates_identical` = **chemin de récupération mensonger**. Pas de compteur loser dédié. | `captures/cap_integrity_structural` (structural) |

#### Cluster 2.D — Migration / self-heal de schéma
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-019 | **F-MIG-PAUSEDAT** (V3 [18]) | 🔴 high | `sqlite_store.py:334` | self-heal rejoue 025 (`DROP TABLE runs`+`SELECT …,NULL`) → **`paused_at` écrasé à NULL** → `resume_run` incohérent. | `captures/cap_integrity_structural` |
| R8-020 | **F-MIG-SCHEMAVER** (V3 [19]) | 🟠 medium | `sqlite_store.py` (`_bootstrap_schema_latest`) | pose `user_version` mais n'insère jamais dans `schema_migrations` → désync après self-heal (diagnostic d'incident 023 impossible). | `captures/cap_integrity_structural` |
| R8-021 | **F-MIG-IDEMPOTENT** (V3 [20]) | 🟠 medium | `migration_manager.py:254` | `_is_idempotent_error` ne couvre que `OperationalError` → un `IntegrityError` (rebuild 021/023/025) **bloque tout le boot**. | `captures/cap_integrity_structural` |
| R8-022 | **F-V6-SCHEMA-IRC** | 🟠 medium | `sqlite_store.py:85-86,110` | `incremental_row_cache` (mig 008) absent de `REQUIRED_SCHEMA_TABLES` ET `SCHEMA_GROUPS['incremental']` → hors filet self-heal : si droppée, ni `_ensure_required_schema` ni `_with_schema_group` ne la recréent → OperationalError. | `captures/cap_integrity_structural` |
| R8-023 | **F-V8-SCHEMA-REGISTRY** | 🟠 medium | `sqlite_store.py:75,102,110` | dérive de registre : `vec_films_hash` (mig **032**) absente de `REQUIRED_SCHEMA_TABLES`/`SCHEMA_GROUPS` (comme `incremental_row_cache` mig 008). **Nuance live** : mig **030** `film_field_locks` EST au registre (fix BUG-002) → le gap réel concerne **008+032, pas 030**. Aveu explicite `repositories/scan.py:67`. | `captures/cap_integrity_structural` ✅ figé |

#### Cluster 2.E — Concurrence / robustesse DB / round-trip
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-024 | **F-V3-E2** | 🔴 high | `retention_cleanup.py:48` · `quarantine_ttl.py:553` · `infra/probe/service.py:723` | 3 sites attrapent `(AttributeError,OSError,RuntimeError,TypeError,ValueError)` mais **PAS `sqlite3.OperationalError`** → un verrou DB transitoire (aggravé par F-DB-01) **tue le thread cron** (retention/quarantaine **définitivement** mortes) ou **avorte le lot de probe** (films scorés au nom seul). | `captures/c3e_cron_db_error_escape.out.txt` ✅ figé (`cron meurt` / contrôle OSError `swallow`) |
| R8-025 | **F-DB-01** | 🔴 high | `infra/db/connection.py:110-112` | le store passe `busy_timeout_ms=8000` ; comme `8000 != 5000`, le bloc back-compat **réécrase** le `busy_timeout` du profil NAS (30000/60000) par 8000 → **SQLITE_BUSY prématuré** sur NAS, y compris pendant ALTER/CREATE INDEX de migration. | `captures/cap_residual.out.txt` ✅ figé (logique back-compat 8000≠5000) |
| R8-026 | **F-V3-E1** | 🟡 low | `infra/state.py:82` | `atomic_write_json` fait `os.replace` **sans retry** → sur Windows, un lecteur concurrent (2 onglets / webview+navigateur / job de fond) fait lever `PermissionError` → **write perdu** (atomicité préservée, pas de corruption). | `captures/c3_concurrent_settings_save.out.txt` ✅ figé (writes lèvent, I1/I2/I3 OK) |
| R8-027 | **F-META-01** | 🟠 medium | `run_data_support.py:132` | `row_from_json` (reload apply post-redémarrage) ne reparse PAS `nfo_runtime` (l'autre désérialiseur `plan_support_core.py:110` le parse) → après restart, détection « durée → autre film » + désambiguïsation ±10 min dégradées. | `captures/meta_roundtrip_planrow.out.txt` ✅ figé (`nfo_runtime` 4242→None) |

#### Cluster 2.F — Autres intégrité
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-028 | **F-H3-01** | 🟡 low | `apply_core.py:340` | `files_identical_quick` = taille + SHA1 des 8 premiers/derniers Mo (full si <16 Mo) → 2 vidéos distinctes à en-tête+pied identiques déclarées `duplicate_identical`, source **déplacée** (réversible, bucket `_review`, pas de delete dur ; collision quasi-impossible sur vraies vidéos). | **à instrumenter** (recette 16 Mo) |
| R8-029 | **F-QTN-MANIFEST** (V3 [2]) | 🟡 low | `quarantine_ttl.py` (`_save_ttl_manifest`) | `write_text` sans `os.replace`/lock → viewer + cron daemon = last-writer-wins (recoupe F-V3-E1). | `captures/cap_residual.out.txt` ✅ figé |
| R8-085 | **F-V7-COLLMKDIR** | 🟠 medium | `apply_core.py:1888` | (chemin FILM) `coll_dir.mkdir(parents=True, exist_ok=True)` créé **AVANT** killswitch MAX_PATH (L1910) + NOOP (L1920) → si un garde `return`/skip → **dossier saga vide orphelin** ; `mkdir` brut (pas `mkdir_counted`) → aucune op MKDIR → rollback ne le supprime jamais ; gated `if not dry_run` → divergence preview/apply. Atteignable au re-apply idempotent d'un film saga conforme. | `captures/v8_collmkdir_repro.out.txt` ✅ figé (`saga_dir_empty_orphan=true`) |

### ███ F3 — SÉCURITÉ (surface résiduelle) ███
> Le bypass loopback est **correctement gaté** (`bind_host=="127.0.0.1"`, prouvé Vague 4A) ; les POST sont **CSRF-protégés**.
> Surface résiduelle = GET non gardés + port ignoré + binaire arbitraire au save.

| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-030 | **F-SEC-01** | 🟠 medium | `rest_server.py:886-999` | `_handle_get` n'appelle ni `_check_auth`, ni `_is_rate_limited`, ni `_is_forbidden_cross_site` → (a) en bind LAN, énumération de films + brûlage quota TMDb non authentifié ; (b) `/api/poster?…&force=1` **supprime le cache + re-DL TMDb**, exploitable en CSRF via `<img src=…&force=1>` même en 127.0.0.1. | `captures/cap_live_sec_a11y` (live forged) |
| R8-031 | **F-SEC-02** | 🟡 low | `rest_server.py:417-421` | `_allowed_origin` compare `hostname` (port+scheme ignorés) pour 127.0.0.1/localhost/::1 → une page sur `http://localhost:9999` POST sur l'API sans token (prérequis : 2ᵉ app locale hostile). | `captures/cap_live_sec_a11y` (live forged) |
| R8-032 | **F-CONF-01** | 🟠 medium | `settings_support.py:1374` ↔ `perceptual_support.py:296-297/333-335` | `_save_section_probe` persiste `ffprobe_path` avec un simple `.strip()` (aucune validation) ; le flux perceptuel l'exécute en `argv[0]` **sans** `_binary_name_allowed` (qui le refuserait côté `get_tools_status`). Asymétrie save/exec. | `captures/cap_false_results` (pure fn) |
| R8-033 | **F-CONF-02** | 🟡 low | `ffmpeg_runner.py:40-49` | `resolve_ffmpeg_path` exécute le **sibling** `ffmpeg.exe` du dossier de `ffprobe_path` sans contrôle (4 sites). | `captures/cap_residual.out.txt` ✅ figé |

### ███ F4 — RÉSULTATS FAUX SILENCIEUX ███

| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-034 | **F-PERC-01** | 🔴 high | `audio_perceptual.py:141-142` | `-v quiet` force le JSON loudnorm (sorti sur stderr/INFO) à disparaître → `analyze_loudnorm`=None → **loudness EBU R128 jamais mesurée**. | `captures/cap_false_results` (argv) |
| R8-035 | **F-PERC-02** | 🔴 high | `audio_perceptual.py:234` | lit le bloc « Overall » d'astats, or Crest/Dynamic range n'y sont **que par canal** → `crest=dynrange=None` → 2 des 6 poids audio **figés à 50** (valeur « parfaite »). | `captures/cap_false_results` (argv) |
| R8-036 | **F-PERC-03** | 🔴 high | `video_analysis.py:90` | `signalstats…,blockdetect,blurdetect` **sans `metadata=mode=print`** → 0 ligne parsée → `blockiness_mean=blur_mean=0.0` → `_score_blockiness(0)=95`, `_score_blur(0)=95` → **score visuel gonflé** (parfait fabriqué). | `captures/cap_false_results` (argv) |
| R8-037 | **F-PERC-04** | 🟠 medium | `run_flow_support.py:564` | `analyze_perceptual_batch` ne transmet pas `should_cancel` ; `api._perceptual_cancel_event` jamais assigné en prod → checks d'annulation **inertes** → `request_cancel` n'arrête pas l'analyse. | `captures/cap_residual.out.txt` ✅ figé |
| R8-038 | **F-H4-01** | 🟠 medium | `quality_score.py:563` | `_normalize_audio_bitrate_kbps` divise par 1000 **seulement si >10000 strict** ; bitrate stocké en bps → un flux ~8 kbps (mono dégradé) lu comme 8000 kbps → **bonus +4 au lieu de malus -3** (inversion de signe). | `captures/cap_false_results` (pure fn) |
| R8-039 | **F-H6-01** | 🟠 medium | `quality_score.py:637` | `_best_audio_track` = `max(channels,bitrate)` (codec-aveugle) vs `duplicate_compare._best_audio` = `max(codec_rank,channels)` → sur film TrueHD/Atmos + piste lossy compat, choisit la lossy → **étiquette codec fausse** (`eac3`/`dts` affiché). **113 films** divergents. | `captures/h6_best_audio_divergence.out.txt` ✅ figé (`865 multi-pistes, 113 divergences`) |
| R8-040 | **F-H5-01** | 🟠 medium | `scene_parser.py:131` | `name.replace('.',' ')` transforme `DD5.1`→`DD5 1` avant `_NOISE_RE` qui ne matche pas → **résidu `DD5 1`/`DDP5 1`/`DD7 1`** pollue la query TMDb → dégrade le match. | `captures/cap_false_results` (pure fn) |
| R8-041 | **F-H7-01** | 🔴 high | `tmdb_client.py:515` | `_cache_set(key, [])` sur réponse `200 + results=[]` + `if cached is not None` (vrai pour `[]`) → film non identifié **~7 jours** à travers les re-scans après UN hoquet TMDb (le fallback stale ne couvre que les erreurs réseau). | `captures/cap_false_results` (stub) |
| R8-042 | **F-V9-DUP-SCALE** | 🔴 high | `doublons.js:297` ↔ `duplicate_compare.py:142` | la carte rend `total_score_a/b` en `${score}/100`, MAIS ce sont des **points head-to-head** (`sum(points_delta>0)` vs `<0`, perdant ~toujours 0) — PAS un 0..100 → gagnant « 30/100 », perdant « 0/100 » même pour 2 bons fichiers. *(seam #4 doublons)* | `captures/cap_contracts_static` |
| R8-043 | **F-V7-PERCEPT-HDR** (V7 [10]-hdr) | 🟡 low | `models.py:382` (`to_dict`) | `hdr_analysis` absent de `to_dict` ET non ajouté en `perceptual_support` → `d.hdr_analysis` undefined → **champ HDR de la modale toujours « sdr »** même sur film HDR. | `captures/cap_contracts_static` |
| R8-044 | **F-MKVTITLE** (V4A [12]) | 🟡 low | `quality_report_support.py:313` (`mkv_title_check.py:53`) | égalité exacte case-insensitive `container_title` vs `proposed_title` → **88 % mismatchent** (release-names à points) → warning `mkv_title_mismatch` quasi toujours actif = **faux signal** qui noie les vrais. | **à instrumenter** (corpus `container_title`, 88 % mesuré V4B) |

### ███ F5 — FEATURES MORTES / CONTRATS DÉSACCORDÉS (les 4 seams + insights) ███

#### Cluster 5.A — Vues mortes (code complet inatteignable)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-045 | **F-V8-ENRICH-DEAD** (V3 [33-35]) | 🔴 high | vue Enrichissement IA (aucune route app.js) | vue complète jamais accessible + ses 3 appels façade échoueraient (`enrichment_facade` n'expose pas `get_status`/`apply_bulk`). | `captures/cap_phantom_config` |
| R8-046 | **F-DEAD-01** | 🟠 medium | `quality-simulator.js:155` · `custom-rules-editor.js:457` | « Simulateur de preset » + « Éditeur de règles custom » inatteignables : seuls hosts `qij.js`/`quality.js` morts (app.js redirige `/qij`→`/accueil`, `/quality`→`/qualite`) ; ~1100 l. de code mort. | `captures/cap_phantom_config` (Playwright redirect + grep) |
| R8-047 | **F-LIBWF-DEAD** (V3 [36]) | 🟠 medium | `initLibraryWorkflow` | page « Bibliothèque workflow 5 sections » inatteignable (`/library`→`/bibliotheque`, jamais montée). | `captures/cap_phantom_config` |
| R8-048 | **F-INDEX-CMT** (V3 [37]) | 🟡 low | `index.html:92` | commentaire de maintenance trompeur (routage inexistant). | `captures/cap_phantom_config` |

#### Cluster 5.B — SEAM #2 : insights/suggestions front↔back désaccordés (vocabulaire)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-049 | **F-V8-INSIGHT-NOTIF** | 🔴 high | `notifications_support.py:254` | miroir insights→Centre de notifications **MORT** : `emit_from_insights` lit `ins.get("code")` mais les insights n'émettent que `{type,…}` → `code` vide → `if not code: continue` saute CHAQUE insight. | `captures/cap_contracts_static` |
| R8-050 | **F-V7-INSIGHT-SUBS** | 🟠 medium | `qualite.js:333` | section « Subs FR manquants » toujours « — » : le front cherche `.includes("subs_missing")` mais le back émet `missing_subtitles` (librarian) / 5 types insights sans match. | `captures/cap_contracts_static` |
| R8-051 | **F-V7-INSIGHT-ROUTE** | 🟡 low | `accueil.js:507-524` | `_INSIGHT_ROUTE_BY_TYPE` keyé sur 8 types (duplicates_probable/films_not_identified/…) — **0/5 match** les types réellement émis → tout clic insight → `/bibliotheque`. | `captures/cap_contracts_static` |
| R8-052 | **F-V8-LIBRARIAN-ROUTE** | 🟡 low | `librarian.py` (92-234) | 4/6 suggestions (`missing_subtitles`/`unidentified`/`low_resolution`/`collections_info`) ont un id divergent de la map front → défaut `/bibliotheque`. | `captures/cap_contracts_static` |

#### Cluster 5.C — SEAM #3 : jumeau `views/film-detail.js` non corrigé (≠ `components/film-detail.js`)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-053 | **F-V8-FILMVIEW-PROBE** | 🔴 high | `views/film-detail.js:261` | lit `probe.video`/`audio[]`/`subtitles[]`/`container_format`/`duration_s` ; producteur `film_support.py:311` met tout sous `detected.*` → sections Vidéo/Audio/Sous-titres/Conteneur **vides** + durée « — ». R7-2 a corrigé le COMPOSANT, pas cette VUE. | `captures/cap_contracts_static` |
| R8-054 | **F-V8-FILMVIEW-CAND** | 🟠 medium | `views/film-detail.js:333-334` | lit `candidates[0].confidence_label`/`.overview` (inexistants sur `Candidate`) → confiance « ? », synopsis jamais rendu. | `captures/cap_contracts_static` |
| R8-055 | **F-V8-FILMVIEW-DIR** | 🟠 medium | `views/film-detail.js:139` | hero lit `candidates[0].director` (inexistant) ; réalisateur en top-level `data.director` (`film_support.py:418`) jamais lu. | `captures/cap_contracts_static` |

#### Cluster 5.D — SEAM perceptual display-path
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-056 | **F-V8-PERCEPT-DISPLAY** | 🟠 medium | `perceptual-modal.js:265` ← `repositories/perceptual.py:357` | la modale charge par DÉFAUT `get_perceptual_details` (report DB nu : métriques sous `d.metrics`, champs probe absents) mais lit `d.codec`/`d.width`/`d.grain_analysis`/`d.breakdown` top-level → **Detail technique / breakdown / bitrate-vs-réso VIDES sur film en cache**. | `captures/cap_contracts_static` |

#### Cluster 5.E — SEAM #4 : rendu doublons (3 renderers dérivés)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-057 | **F-V9-DUP-DECISION** | 🔴 high | `doublons.js:194` ↔ `run_flow_support.py:1744` | après « Garder A/B », le badge « Décidé » disparaît au refresh : `check_duplicates` ne joint jamais les décisions (`winner_decided`/`winner_side` = 0 hit back) → `decidedCount=0`. Décision persistée+honorée à l'apply mais **invisible en UI**. | `captures/cap_contracts_static` |
| R8-058 | **F-V9-DUP-UNITS** | 🟠 medium | `doublons.js:100` ↔ `duplicate-comparator-modal.js:57` ↔ `lib-duplicates.js:215` | **3 formateurs de taille divergents** pour 1 donnée : « 1.5 Go » (décimal sur math binaire) / « 1.50 Gio » / `fmtBytes` locale-aware. En locale EN, l'économie reste FR dans Doublons. Helper centralisé EXISTE, 2/3 ne l'adoptent pas. | `captures/cap_contracts_static` |
| R8-059 | **F-V4B-DUP1** | 🟠 medium | `doublons.js:367` ← `run_flow_support.py:1446` | lignes Codec/Résolution/Audio des cartes A/B **jamais affichées** : `_quality_info_for_row` ne renvoie que `{score,tier}`. | `captures/cap_contracts_static` |

#### Cluster 5.F — Sérialiseur cache + contrats historique
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-060 | **F-V9-CACHE-STATS** | 🟠 medium | `plan_support_core.py:168` ↔ `:208` | `stats_snapshot_for_cache` capture 13 champs mais OMET `films_rejected_ext/size/name`, `root_level_films_seen`, `tv_episodes_seen`, `folders_rejected_scandir_error` → sur cache HIT incrémental, contribution des dossiers cachés **perdue** → « Diagnostic scan » sous-compte + warning « films à la racine » supprimé à tort. | `captures/cap_contracts_static` |
| R8-061 | **F-HIST-DUP** (V7 [11]) | 🟡 low | `history_support.py:337` | builder `duplicates_decided` ne produit que `{title,year,winner}` → front lit `g.winner_label`+`g.size_savings` = undefined → label gagnant + gain d'espace jamais affichés (onglet Doublons Inspecteur Historique). | `captures/cap_contracts_static` |
| R8-062 | **F-HIST-FILM** (V7 [12]) | 🟡 low | `history_support.py:317` | builder `films` ne produit que `{film_id,title,year,tier,score}` → front lit `film.decision`/`.status`/`.is_duplicate` = undefined → statut toujours au défaut (onglet Films). | `captures/cap_contracts_static` |

#### Cluster 5.G — Config fantôme (toggles write-only, 0 consommateur)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-063 | **F-PROM-02** | 🟠 medium | `parametres.js:151-152` | `cleanup_orphans` + `cleanup_empty_folders` echo-persistés seulement, absents de `Config`/`build_cfg_from_settings`, 0 consommateur → cocher « nettoyer orphelins / supprimer dossiers vides » **ne supprime rien**. | `captures/cap_phantom_config` |
| R8-064 | **F-PROM-01** | 🟠 medium | `parametres.js:105` | `auto_approve_enabled` inerte : `get_auto_approved_summary` 0 appelant UI ; le bouton « Approuver les sûrs » utilise `_state.autoThreshold` seul. | `captures/cap_phantom_config` |
| R8-065 | **F-PROM-03** | 🟡 low | `parametres.js:128` | sélecteur « Séparateur » inerte en preset défaut (`{sep}` absent des templates) ; `subtitle_lang_priority` fantôme (vraie clé `subtitle_expected_languages`). | `captures/cap_phantom_config` |
| R8-066 | **F-KPI-DUPGROUPS** (V4A [21]) | 🟠 medium | `traitement.js:245` ← `dashboard_support.py:542` | `k.duplicates_groups` absent des kpis live (12 clés) → stat « Groupes de doublons » toujours 0 + fallback estim. moves faussé. | `captures/cap_phantom_config` |
| R8-067 | **F-CFG-ANIM** (V4A [27]) | 🟠 medium | `parametres.js:277` | `animations_enabled` persisté, **0 consommateur DOM/CSS** (coupées seulement par `@media prefers-reduced-motion`) → hint « interface 100 % statique » mensonger. | `captures/cap_phantom_config` |
| R8-068 | **F-CFG-WORKERS** (V3 [28]) | 🟠 medium | `parametres.js` (`global_workers`) | champ « Nombre de workers globaux » inerte (0 consommateur). | `captures/cap_phantom_config` |
| R8-069 | **F-CFG-NOTIF** (V4A [29]) | 🟠 medium | `parametres.js:215` | `desktop_notifications_enabled` persisté, 0 consommateur (les notifs sont pilotées par `notifications_enabled`). | `captures/cap_phantom_config` |
| R8-070 | **F-CFG-RETENTION** (V3 [30]) | 🟠 medium | `parametres.js` (`retention_days`) | « Rétention scores et analyses (jours) » ne purge rien : seul consommateur `prune_disk_cache` jamais appelé en prod ; les crons lisent `history_retention_days`. | `captures/cap_phantom_config` |
| R8-071 | **F-CFG-NAMETPL** (V3 [31]) | 🟡 low | `parametres.js` (`naming_template`) | « Template général » persisté mais non lu (moteur lit `naming_movie_template`/`naming_tv_template`). | `captures/cap_phantom_config` |
| R8-072 | **F-CFG-EFFECTS** (V3 [32]) | 🟡 low | `parametres.js` (`effects_mode`) | gap inverse : `effects_mode` appliqué par app.js sans contrôle dans parametres.js. | `captures/cap_phantom_config` |

#### Cluster 5.H — TV-apply : préview/édition (contrat utilisateur)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-073 | **F-V6-TV-DRYRUN** | 🔴 high | `apply_core.py:2238-2247` | en dry_run, `atomic_move` ET `record_apply_op` sont dans `if not dry_run:` → **aucune op enregistrée pour les épisodes TV en preview** alors que `res.moves += 1` incrémenté inconditionnellement → preview TV vide + compteur faux. | `captures/cap_tv_parity` |
| R8-074 | **F-V6-TV-UIEDIT** | 🟠 medium | `apply_core.py:1567` | apply_tv_episode nomme depuis `row.proposed_*` ; apply_single reçoit `new_title/new_year` de la décision UI → **toute correction titre/année saisie sur un épisode TV est silencieusement ignorée**. | `captures/cap_tv_parity` |
| R8-075 | **F-V6-TV-ANIME** | 🟠 medium | `tv_helpers.py:95` (commentaire :92) | « Episode N » (numérotation absolue anime, sans saison) → `season=None` → `apply_tv_episode` force `Saison 00`/`S00E{ep}` → anime classé dans les **specials**. | `captures/cap_tv_parity` |

#### Cluster 5.I — États UI (course / fuite — comportemental)
| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-083 | **F-PROC-POLL** (V4A [11]) | 🟠 medium | `app.js:281` · `processing.js:485,876` | naviguer vers `/processing` pendant un run laisse une **boucle de polling fuyante** (`run/get_status` toutes les 2 s) : `unmountProcessing()` existe mais jamais câblé — le routeur prend le **retour de `init()`** comme cleanup, or `initProcessing` est `async` → retourne une Promise (pas une fonction) → cleanup ignoré → le poll **s'empile à chaque visite**. | **à instrumenter** (Playwright, navigation répétée) — code-indiqué |
| R8-084 | **F-RESET-RACE** (V5 C1 [10]) | 🟠 medium | `parametres.js:2029` | reset des params **sans `clearTimeout(_state.saveTimer)`** → si le debounce autosave (500 ms) fire pendant le round-trip du reset, l'ancienne valeur est re-postée → **reset silencieusement annulé**. CONFIRMÉ-mécanisme V5 (`save_settings` a tiré à t=514 ms après un reset cliqué à ~370 ms). | **à instrumenter** (Playwright timing) — mécanisme prouvé V5 |

### ███ F6 — COSMÉTIQUE / a11y / i18n / confort / hygiène ███

| N° | ID | sév | fichier:ligne | symptôme | capture |
|---|---|---|---|---|---|
| R8-076 | **F-OMDB-CONTRAST** (V4B [13]) | 🟡 low | `components.css:7634` | `.omdb-status--error` : ratio WCAG **2,94:1** dans les 5 thèmes (< AA 4.5 et AA-large 3.0) → message « Clé API invalide » peu lisible. | `captures/cap_live_sec_a11y` → **TODO Playwright/getComputedStyle** (à instrumenter) |
| R8-077 | **F-V4B-I18N** | 🟡 low | `i18n.js:38` (`_FALLBACK_FR`) | `sidebar.nav.doublons` **absent des 2 locales** (fr.json ET en.json), n'existe que dans `_FALLBACK_FR` → en EN, « Doublons » reste en français (seul item non traduit). | `captures/cap_live_sec_a11y` (key-diff) |
| R8-078 | **F-RESETMODAL-FOCUS** (V5 C3) | 🟡 low | `parametres.js:1896` | `_openResetModal` construit un overlay custom (`appendChild`) **sans `trapFocus`** → la modale reset n'a pas de piège de focus (le focus s'échappe vers le fond). Les modales standard (`modal.js`) sont saines. | `captures/cap_live_sec_a11y` (à instrumenter Playwright) |
| R8-079 | **F-H5-03** | 🟡 low | `core.py:168-170/478-494` | pack TV à convention non-standard (`Show.101.mkv`=S01E01, `E01` seul, ` - 01`) non détecté comme série → chaque épisode planifié comme film distinct. | `captures/cap_residual.out.txt` ✅ figé (`looks_tv_like` False sur 101/E01/- 01) |
| R8-080 | **F-H7-02** | 🟡 low | `jellyfin_sync.py:217-248` | après apply d'un film vu, un 503 transitoire sur `PlayedItems` laisse le flag « vu » non restauré et non re-tenté dans ce run (`client.mark_played` échoue → `result.errors++`, pas de re-queue). WARN émis, récupérable par re-sync. | `captures/cap_residual.out.txt` ✅ figé |
| R8-081 | **F-TEST-01** | 🟠 medium | `tests/test_auto_install.py:37` | `assertTrue(d.exists() or True)` toujours vrai → `test_creates_dir` passe quoi qu'il arrive (**test menteur** qui masquerait une régression R8). **À corriger AVANT de s'appuyer sur ce test en R8.** | `captures/cap_residual.out.txt` ✅ figé (table de vérité `x or True`) |
| R8-082 | **F-0.5-02** | 🟠 medium | `docs/internal/observe/` | bloat git : **771 Mo / 1608 fichiers** trackés non ignorés → clones/CI lourds + surface de fuite future. (PAS une fuite de secret actuelle — réfutée en live, voir non-régression.) | `git ls-files`/`du -sh` (mesuré, F-0.5-02 rapport) |
| R8-086 | **F-TEST-FLAKY-PERC** | 🟡 low | `tests/test_perceptual_parallel.py` (`test_video_and_audio_tasks_run_via_pool`) | test **flaky** (assertion de parallélisme via `time.sleep(0.1)`, sensible à l'ordonnancement) : ~3/9 PASS en isolation. Faux signal de régression (masque/bruite la non-régression R8). Découvert en F2-a. **NON corrigé** (F6/durcissement-tests). | run x6 = 2 PASS / 4 FAIL (cf R8_CORRECTIONS F2-a) |

---

## 2. CAPTURES DE RÉFÉRENCE (l'état cassé, mesuré — rejouable)

### 2.1 Captures DÉJÀ FIGÉES (rejouables immédiatement)
> Lancer : `PYTHONPATH=. .venv313/Scripts/python.exe docs/internal/audit_horizons/proofs/<script>.py`.
> Sortie figée = `./captures/<script>.out.txt`. Chaque sortie = la **photo de l'état cassé** que R8 doit inverser.

| Capture (sortie figée) | Findings prouvés | Observation cassée figée (résumé) |
|---|---|---|
| `captures/v9_coll_atomic_repro.out.txt` | R8-001 | `half_applied=true, sidecars_moved=true, video_stuck=true, no_rollback=true, **dedup_poisoned=true**` |
| `captures/v5_tv_apply_repro.out.txt` | R8-004, R8-005 | `B1_sidecars_orphelins=true` ; 3 ops MOVE_FILE `src_sha1=<absent>` → `B2_ops_sans_sha1=true` |
| `captures/v8_collmkdir_repro.out.txt` | **R8-085** (F-V7-COLLMKDIR, chemin film) | `saga_dir_empty_orphan=true, no_mkdir_op=true, movie_skipped=true` (dossier saga vide orphelin) |
| `captures/c3e_cron_db_error_escape.out.txt` | R8-024 | T1 `cron meurt` (sqlite re-levé) / T2 contrôle OSError `swallow` → harnais discrimine ; `OperationalError_base=DatabaseError` |
| `captures/meta_roundtrip_planrow.out.txt` | R8-027 | `champs perdus au reload: ['nfo_runtime']` (4242→None) |
| `captures/h6_best_audio_divergence.out.txt` | R8-039 | `multi-pistes=865 divergences=113` (GATE falsifiabilité OK) |
| `captures/c3_concurrent_settings_save.out.txt` | R8-026 | atomicité I1/I2/I3 OK, writes lèvent `PermissionError` (write perdu, pas de corruption) |

### 2.2 Captures NOUVELLES (workflow `wf_2f42cbb0-148` + `cap_residual` — TERMINÉ)
> 6 familles (workflow) + 1 résiduelle, chacune un script + sortie figée sous `./captures/`. Mapping RÉEL
> (ce qui est effectivement capturé ; détail + sorties figées en **§5**) :
> - `cap_tv_parity.out.txt` → R8-003,004,005,006,007,008,009,010,011,073,074,075 (**12/12**, fixtures jetables)
> - `cap_integrity_structural.out.txt` → R8-012,013,014,015,017,018,019,020,021,022,023 (**9 blocs**, structural)
> - `cap_false_results.out.txt` → R8-032,034,035,036,038,040,041 (**7/7**, pures fonctions + argv ffmpeg + stub TMDb)
> - `cap_contracts_static.out.txt` → R8-042,043,049,050,051,052,053,054,055,056,057,058,059,060,061,062 (**16/16**)
> - `cap_phantom_config.py.out.txt` → R8-045,046,047,048,063,064,065,066,067,068,069,070,071,072 (**14/14**)
> - `cap_live_sec_a11y.out.txt` → R8-030,031,077 (**3/3 live**) ; R8-076 **TODO Playwright**
> - `cap_residual.out.txt` → R8-016,025,029,033,037,079,080,081 (**8/8**, static/pure-fn ; complète les angles non assignés aux 6 familles)

### 2.3 Captures À INSTRUMENTER avant de corriger (repro non figé — outillage runtime requis)
- **R8-076 F-OMDB-CONTRAST** : ratio WCAG runtime → Playwright + `getComputedStyle` (compositing alpha par thème).
  Mesuré 2,94:1 en V4B, non figé en script. Sélecteur `.omdb-status--error` `components.css:7634-7638` confirmé.
- **R8-078 F-RESETMODAL-FOCUS** : piège de focus modale reset → ouverture UI + nav clavier (Tab/Shift+Tab/Escape) Playwright.
- **R8-083 F-PROC-POLL** : fuite de polling `/processing` → navigation répétée Playwright (cleanup orphelin confirmé en code).
- **R8-084 F-RESET-RACE** : course reset↔autosave → timing Playwright (mécanisme prouvé V5, `save_settings` t=514 ms).
- **R8-002 F-QTN-GOV** : run réel écrivant `run_dir/_review` puis rétention-runs purgeant → fixture jetable à monter.
- **R8-028 F-H3-01** : `files_identical_quick` faux positif → fixtures ≥16 Mo à en-tête+pied identiques, milieu différent (low).
- **R8-044 F-MKVTITLE** : taux de faux `mkv_title_mismatch` → balayage corpus `container_title` (88 % mesuré V4B, à figer).
- **R8-034/035/036 F-PERC-01/02/03** : argv figé (`-v quiet` / pas de `metadata=mode=print`) → **valider au VRAI ffmpeg**
  (repro binaire réel déjà fait en découverte, à re-figer en baseline avant fix — la fixture synthétique du test unitaire ment).

---

## 3. CLASSEMENT F1-F6 + UNIFICATIONS POSSIBLES (ordre de correction R8)

> Le classement EST l'ordre des tables du §1. Synthèse des **unifications** (corriger une cause-racine, pas N symptômes) :

- **F1** (R8-001..002) — atomicité apply collection + gouvernance quarantaine. **Unif.** : un seul invariant
  « tout-ou-rien intra-row + ne pas empoisonner le dedup avant un move réussi ».
- **F2.A** (R8-003..011, 073..075) — **TV-apply = UN chantier de mise à parité** avec le chemin film (grille 13 gardes,
  Vague 7). **Unif.** : faire passer `apply_tv_episode` par `move_file_with_collision_policy` + `mkdir_counted` +
  src_sha1/size + killswitch `_longest_inner` + record_op en dry_run + leftovers + réalignement sidecars. ~13 findings → 1 fix.
- **F2.B** (R8-012..016) — rollback/statut. **Unif.** : un seul writer de statut (op-level `undo_status` ET batch-level
  `apply_batches.status`) + reconcile élargi à `rollback_status='IN_PROGRESS'`/`FAILED`.
- **F2.C** (R8-017..018) — helpers loser : les déplacer DANS la boucle/try-except + compteur loser dédié.
- **F2.D** (R8-019..023) — self-heal de migration : préserver `paused_at`, insérer dans `schema_migrations`, élargir
  `_is_idempotent_error` à `IntegrityError`, **tenir le registre `REQUIRED_SCHEMA_TABLES`/`SCHEMA_GROUPS` à jour** (gaps réels **008 + 032** ; 030 déjà couvert).
- **F2.E** (R8-024..027) — taxonomie d'exceptions : ajouter `sqlite3.Error` aux 3 tuples + boucler les crons ; ne pas
  écraser le busy_timeout NAS ; retry `os.replace` ; ajouter `nfo_runtime` à `row_from_json`.
- **F3** (R8-030..033) — appliquer `_check_auth/_is_rate_limited/_is_forbidden_cross_site` aux GET sensibles ; exiger
  port+scheme dans la branche loopback ; `_binary_name_allowed` au save ET dans le perceptuel (sibling inclus).
- **F4** (R8-034..044) — perceptuel : `-v quiet`→`info`, crest/dynrange par-canal, `metadata=mode=print`, propager
  `should_cancel`. Scoring : diviser le bitrate bps, départager l'audio par rang codec. Cache TMDb : ne pas cacher `[]`.
- **F5** — **4 seams + insights = chantiers de mise à parité de contrat** (specs = les 4 grilles de parité Vague 10) :
  **Unif. forte** : (1) supprimer le jumeau `views/film-detail.js` (réutiliser le render du composant) ; (2) une seule
  forme perceptuelle (`get_perceptual_details` = forme aplatie de `to_dict` + probe) ; (3) `check_duplicates` joint
  `duplicate_decisions` + échelle de score unique + **les 3 renderers adoptent `core/format.js fmtBytes` (helper EXISTANT)** ;
  (4) snapshot/replay du cache alignés ; (5) câbler ou supprimer les vues mortes + toggles fantômes ; (6) un vocabulaire
  d'insights unique front↔back (5 types back ⟷ map front + 3ᵉ consommateur notifications).
- **F6** — i18n (ajouter `sidebar.nav.doublons` aux 2 locales), contraste OMDb, focus-trap modale reset, hygiène git
  (`.gitignore docs/internal/observe/`), **corriger F-TEST-01 d'abord** (test menteur).

---

## 4. SUITE DE NON-RÉGRESSION DE RÉFÉRENCE (chemins SAINS à NE PAS casser)

> Captures du comportement CORRECT actuel. Un fix R8 ne doit faire basculer aucune de ces observations.

| Garde anti-régression | Capture (sortie figée) | Invariant à préserver |
|---|---|---|
| **Chemin film nominal** (apply_single atomique `folder.rename`) | réf. `../AUDIT_HORIZONS_2026-06-15.md` V7 grille (réf saine) | un fix TV ne doit pas dégrader le chemin film (collision policy, leftovers, sidecars alignés). |
| **Bornes & cohérence tier du scoring** | `captures/meta_score_bounds_monotonic.out.txt` | **R1 bornes VERT** (score∈[0,100], int, 0 NaN, tier valide) + **R3 monotonie bitrate VERT**. ⚠️ **R2 ROUGE = FAUX ORACLE** (pénalité bitrate↔résolution intentionnelle `penalty_4k_light`) → **NE PAS** « corriger » R2. |
| **Round-trip settings save→load** | `captures/meta_settings_roundtrip.out.txt` | 97/99 clés identiques ; 2 divergences = normalisations légitimes (`composite_score_version 3→2` clamp ; `remember_key True→False` dérivé du secret absent). Un fix ne doit pas casser ces normalisations ni perdre d'autres clés. |
| **Migrations (DB courante + vrai vieux schéma v27)** | `captures/c3_migrations_old_db.out.txt` | upgrade v27→v31 **lossless + idempotent**, 19→23 tables, 0 perte ; self-heal idempotent. Un fix `_is_idempotent_error`/`schema_migrations`/registre ne doit pas régresser ceci. |
| **Quarantaine TTL (mécanisme P0 corrigé)** | `captures/c1_quarantine_ttl_fix.out.txt` | first-seen=now (pas de purge au 1ᵉʳ cycle) ; purge à T+TTL ; ttl=0 no-op. P0 314 corrigé — ne pas régresser en touchant F-QTN-GOV. |
| **Rollback QUARANTINE_\*** (P0 corrigé) | `captures/c1_rollback_quarantine_revert.out.txt` | revert réel dst→src (DONE) ; DELETE→SKIPPED ; dst absent→SKIPPED. Un fix RB1/RB2 ne doit pas casser le revert. |
| **Atomicité écriture settings** | `captures/c3_concurrent_settings_save.out.txt` | I1/I2/I3 : **jamais de JSON corrompu** sous lecture concurrente. Le retry `os.replace` (fix R8-026) doit préserver l'atomicité. |
| **Auth loopback / CSRF POST** | `captures/cap_live_sec_a11y` (à figer) | bypass gaté `bind_host=="127.0.0.1"` ; **POST cross-site → 403** (CSRF). Un fix GET (R8-030) ne doit pas ouvrir les POST ni casser le bypass loopback légitime. |
| **Couleurs tiers (5 thèmes)** | réf. V4B getComputedStyle runtime | `--tier-platinum/-gold/-silver/-bronze` = #E5E4E2/#FFD700/#C0C0C0/#CD7F32 **exacts** dans aaa/cinema/luxe/neon/studio. INVARIANT dur. |
| **Parité clés i18n** | réf. V4B (fr.json 746 == en.json 746) | 0 clé manquante (sauf le cas `sidebar.nav.doublons` = R8-077). Ajouter cette clé ne doit pas déséquilibrer la parité. |
| **a11y baseline Accueil** | réf. V4B | 14 régions `aria-live=polite`, 0/21 bouton sans nom, 0 img sans alt, Escape ferme+restaure focus. À préserver. |
| **Pas de fuite de secret git** | `git grep` (F-0.5-01 réfuté) | 0 token/Bearer/clé API en clair dans `docs/internal/observe` tracké. `.gitignore` du dossier (fix R8-082) ne doit rien exposer. |
| **Sécurité torrents** | réf. plan (invariant) | NE JAMAIS renommer le fichier vidéo d'un film (le rename TV épisode est une action dédiée distincte, R8-004 ≠ violation). |

---

## ANNEXE — LATENTS / RÉFUTÉS / INTENTIONNELS (NE PAS corriger en R8)
> Tracés pour transparence : ce ne sont **pas** des fix-targets. Toute « correction » ici serait une régression.

| ID | statut | raison |
|---|---|---|
| V3 [14] probe_quality null→UNKNOWN | **LATENT** | distribution réelle `{FULL:1042, PARTIAL:2}`, **0 null** ; branche jamais atteinte en prod. |
| V3 [1] / V4A TTL path-reset | **LATENT** | aucun flux vivant ne re-déplace un fichier déjà suivi vers un nouveau rel (réorg user hors-bande seule). |
| V3 [3] fallback st_mtime | **LATENT** | présent mais inerte sur le chemin TTL réel (code piège futur). |
| V4A [22] `display_tier` | **RÉFUTÉ** | `display_tier \|\| tier_v2 \|\| r.tier` → fallback propre (lecture morte, pas un défaut user). |
| V4A [23] rename TV preview | **RÉFUTÉ/intentionnel** | action TV explicite ; la sécurité torrent vise les films. |
| V3 [6] revert QUARANTINE SKIP | **RÉFUTÉ/intentionnel** | garde TOCTOU anti-écrasement (WARN émis). |
| F-H5-02 `windows_safe` sans séparateur | **INTENTIONNEL+TESTÉ** | délibéré, verrouillé par `test_path_utils_v77.py` ; l'exemple `Mission:Impossible` de la claim est inexact. |
| F-V6-MKDIR-REV (ops MKDIR `reversible=False`) | **INTENTIONNEL probable** | ne pas supprimer un dossier potentiellement non-vide au rollback ; résidu de dossiers vides toléré. |
| R2 monotonie résolution (oracle métamorphique) | **FAUX ORACLE** | la « violation » à bitrate fixe = pénalité bitrate↔résolution intentionnelle (cf non-régression). |
| V3 [17] worker recompute | **RÉFUTÉ** | rattrape correctement son boundary (robuste). |
| V3 [24][25][26] contrats `get_status`/preview | **RÉFUTÉ** | intacts ; `r.decision` undefined dégrade proprement. |
| Migration 032 (tirets) | **LATENT** | `SqliteVecAdapter` = scaffold `NotImplementedError`, flag `similar_films` OFF. |
| F-0.5-01 fuite secret observe | **RÉFUTÉ (live)** | 0 token/Bearer en clair dans les fichiers trackés (hypothèse « quasi-certaine » fausse). |

---

## 5. STATUT DES CAPTURES NOUVELLES (workflow `wf_2f42cbb0-148` — TERMINÉ)

> 6 scripts produits + sortie figée, **tous exit 0**, file:line **re-vérifiés contre la source réelle**
> (garde anti-drift). Panel de complétude : **0 finding confirmé orphelin** après ajout de R8-083/R8-084.
> Tous les scripts respectent read-only strict (fixtures tempfile / stubs / grep ; serveur `--api` laissé UP).

| Script (sortie figée) | Findings capturés | État cassé reproduit | Drifts corrigés |
|---|---|---|---|
| `captures/cap_tv_parity.py` → `.out.txt` | R8-003,004,005,006,007,008,009,010,011,073,074,075 | **12/12** (comportemental sur fixtures + structural) | TV-ANIME `tv_helpers.py:95` (≠:92 commentaire) |
| `captures/cap_integrity_structural.py` → `.out.txt` | R8-012,013,014,015,017,018,019,020,021,022,023 | **9 blocs** (structural grep + positions try/except) | SCHEMA-REGISTRY = **008+032** (030 déjà au registre) ; 025 `paused_at` NULL ligne 64 |
| `captures/cap_false_results.py` → `.out.txt` | R8-032,034,035,036,038,040,041 | **7/7** (pures fonctions + argv ffmpeg + stub TMDb) | `clean_title_guess` vit dans `title_helpers.py:254` (≠ scene_parser) ; `_save_section_probe` `settings_support.py:1366` |
| `captures/cap_contracts_static.py` → `.out.txt` | R8-042,043,049,050,051,052,053,054,055,056,057,058,059,060,061,062 | **16/16** (contract-diff consommateur↔producteur via `dataclasses.fields`) | FILMVIEW-DIR `film-detail.js:139` (≠:137) ; `stats_snapshot_for_cache` def :167 ; `get_perceptual_report` (≠details) |
| `captures/cap_phantom_config.py` → `.py.out.txt` | R8-045,046,047,048,063..072 | **14/14** (0-consommateur + redirections vues mortes) | clé réelle `worker_count` (≠`global_workers`, doc-only) ; [30] = `prune_disk_cache` 0 appelant |
| `captures/cap_live_sec_a11y.py` → `.out.txt` | R8-030,031,077 + R8-076 (TODO) | **3/3 live** (POST evil→403, GET poster evil→**200**, localhost:9999→**200**) ; I18N clé absente 2 locales | locales = `locales/fr.json`+`locales/en.json` (≠`web/locales/`) ; i18n `web/dashboard/core/i18n.js:38` |
| `captures/cap_residual.py` → `.out.txt` | R8-016,025,029,033,037,079,080,081 | **8/8** (static grep + pures fonctions ; angles non assignés aux 6 familles) | `ffmpeg_runner.py` → `cinesort/domain/perceptual/` ; `jellyfin_sync.py` → `cinesort/app/` (`mark_played`) ; `looks_tv_like(folder,videos)` |

**Observations live notables (sécurité)** : `POST /api/run/get_status` Origin=`evil.example` → **403** (CSRF OK) ;
`GET /api/poster?id=550 Origin=evil` → **200** (GET non gardé = R8-030) ; `POST … Origin=http://localhost:9999`
→ **200** (port ignoré = R8-031). Token REST masqué dans la sortie (jamais en clair).

**Nuance honnête conservée dans `cap_false_results`** (R8-034..036 perceptuel) : les flags `-v quiet` / l'absence
de `metadata=mode=print` sont capturés depuis l'**argv construit** (pas d'exécution ffmpeg) ; les résultats
None/0-frame supposent le comportement stderr **documenté** de ffmpeg (loudnorm JSON au niveau info ; signalstats
via metadata=print). Le bloc Overall d'astats (R8-036) est **build-dépendant** : la fixture est représentative,
pas une assertion sur tous les builds. C'est ce qui explique que le **test unitaire du projet passe** (il nourrit
une fixture synthétique `Overall Crest factor:` que ffmpeg réel n'émet pas). → R8-034..036 = à **valider au vrai
ffmpeg** en R8 (le repro binaire réel existe déjà côté découverte, cf. `../AUDIT_HORIZONS` F-PERC-01/02/03).

### Artefacts cosmétiques (sans impact sur la preuve)
- `cap_phantom_config` a figé sa sortie en `cap_phantom_config.py.out.txt` (double extension) — contenu intègre.
- Quelques `.out.txt` affichent les em-dash/flèches Unicode en `�` (redirection console cp1252) ; toutes les
  evidences de code sont en ASCII, donc lisibles. `cap_tv_parity` a été figé en UTF-8 via le tool Bash.

### Findings À INSTRUMENTER avant correction R8 (repro live non figé)
| ID | raison | ce qui existe déjà |
|---|---|---|
| R8-076 F-OMDB-CONTRAST | ratio WCAG runtime → Playwright + `getComputedStyle` (compositing alpha) | ratio 2,94:1 mesuré V4B, sélecteur `.omdb-status--error` `components.css:7634-7638` confirmé |
| R8-078 F-RESETMODAL-FOCUS | piège de focus modale reset → ouverture UI + nav clavier Playwright | overlay custom sans `trapFocus` confirmé `parametres.js:1896` |
| R8-083 F-PROC-POLL | fuite de polling → navigation répétée `/processing` Playwright | cleanup orphelin confirmé (code) `processing.js:876` |
| R8-084 F-RESET-RACE | course reset↔autosave → timing Playwright déterministe | mécanisme prouvé V5 (save_settings t=514 ms) |
| R8-002 F-QTN-GOV | run réel écrivant `run_dir/_review` puis rétention-runs purgeant → fixture jetable | mécanisme TTL sain prouvé (`c1_quarantine_ttl_fix`) ; gouvernance prouvée par chemins |
| R8-028 F-H3-01 | faux positif `files_identical_quick` → fixtures ≥16 Mo (en-tête+pied identiques, milieu différent) | logique 8/8/16 Mo confirmée en code (low) |
| R8-044 F-MKVTITLE | taux de faux `mkv_title_mismatch` → balayage corpus `container_title` (copie RO probe_cache) | 88 % mesuré V4B ; égalité exacte case-insensitive confirmée |
| R8-034/035/036 | basculer du repro argv au **vrai ffmpeg** (déjà fait en découverte, à figer en baseline) | commandes exactes + sorties stderr réelles dans `../AUDIT_HORIZONS` |

---

## 6. VERROU MÉTHODOLOGIQUE (rappels pour R8)
- **Vert mocké ne prouve rien** : F-TEST-01 (R8-081) est un test **menteur** ; le corriger **AVANT** de s'appuyer
  sur la suite. La fixture perceptuelle synthétique (R8-034..036) est un autre vert trompeur.
- **R2 monotonie résolution = FAUX ORACLE** : `meta_score_bounds_monotonic` vire ROUGE sur R2 par **conception**
  (pénalité bitrate↔résolution voulue) → **NE PAS** « corriger » R2 (ce serait une régression). Voir §4.
- **Aucune référence sacrée** (UPGRADE 1) : le chemin film « sain » (réf TV) est lui-même non-atomique sur les
  collections (R8-001). Un fix TV qui copie le chemin film doit copier le **chemin film corrigé**, pas l'actuel.
- **Clé dédup** = `fichier:ligne ∪ signature-cause-racine` (maintenir si findings additionnels).

---

> **BASELINE CAPTURÉE — 85 findings figés (R8-001..R8-085, + 12 latents/réfutés en annexe), 70 observations
> cassées rejouables réparties sur 14 scripts de capture (7 proofs historiques + 6 familles workflow + 1 résiduelle)
> + 5 captures de non-régression, familles F1-F6 classées, suite de non-régression posée. Prêt pour R8.**
>
> **Récap par famille** : F1 perte-données = **2** (2 perte/récup, 1 figée) · F2 intégrité = **28** (10 perte/récup,
> 6 figées) · F3 sécurité = **4** (3 live figées) · F4 résultats faux = **11** (8 figées) · F5 features mortes/
> contrats/UI = **33** (30 figées) · F6 cosmétique/a11y/i18n/hygiène = **7** (3 figées). **8 findings restent à
> instrumenter** (R8-076, R8-078, R8-083, R8-084, R8-002, R8-028, R8-044 + figer R8-034..036 au vrai ffmpeg) —
> listés §2.3/§5. **Code 100 % intact** (0 correction/commit/push, serveur `--api` UP). Leurres campagne **0/28**.
