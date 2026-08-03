# Roadmap Vague P - Solidite & controle (Apply atomique + verrous)

> **Branche** : `fix/v150-batch-bugs`
> **Date** : 2026-06-01
> **Statut** : **GO_WITH_FIXES** - fixes critique appliques sur VP-E (canonical) et VP-D (cablage save_validation)
> **Total revise** : 7 items / **103h reel** + **25.75h buffer integration (25%)** = **128.75h** ceiling
> **Verdict source** : Workflow Deep (recherche TRaSH 2026 + Jellyfin LockedFields + SQLite 2026) + Logic adversariel (GO_WITH_FIXES)
> **Tag** : `mini-recovery-p` POSE a la fin de ce document (mini-recovery, pas tag de release)

---

## 1. Introduction

Apres la Vague O (performance & infra), la **Vague P** regroupe **7 chantiers** centres sur la **solidite transactionnelle**, le **scoring qualite multi-axes** et le **controle utilisateur** :

1. **VP-A** Apply atomique forward rollback (flag opt-in, migration 029, module `apply_rollback`).
2. **VP-B** Hierarchie qualite tier-trumps (TRaSH/Radarr 2026, overlay non-breaking sur scoring V1).
3. **VP-C** Field locks Jellyfin-style (migration 030, `merge_metadata` resistant au rescan).
4. **VP-D** Decisions tri-etat accepted/rejected/deferred (migration 031, backward compat `{ok:bool}` ABSOLUE).
5. **VP-E** Refactor `plan_support.py` (decoupe haute LOC en sous-modules thematiques).
6. **VP-F** Quality profiles facade & UI parametres (TRaSH-compatible, import/export Recyclarr YAML).
7. **VP-G** Audit integration finale UI library (cablage end-to-end VP-A/C/D).

**Convergences fortes 2026** :
- **TRaSH/Radarr** : "Quality Trumps All" hierarchique multi-axes (Source > Codec > HDR > Audio > Group) + Custom Format Groups + Recyclarr YAML.
- **Jellyfin LockedFields** : verrous champ-par-champ + `merge_metadata` pour resister au rescan/refresh (bug Jellyfin #15549 lecon).
- **SQLite 2026 PEP 249** : `connect(autocommit=False)` pour rollback FS+DB coordonne.

---

## 2. Fixes appliques apres critique adversariale

### Fix #1 - VP-E canonical : repositionnement en pur refactor

**Critique** : la justification "logique canonical inline dans `title_helpers.py`" est FAUSSE - `grep -i canonical cinesort/domain/title_helpers.py` retourne 0 occurrence. Les fonctions presentes sont `extract_year`, `clean_title_guess`, `title_prefix_before_parenthesized_year`, `_norm_for_tokens`, `tokens`, `seq_ratio`, `title_match_score`, `_title_similarity`. Aucune n'est appelee "canonical" et `to_canonical_v2_tier` (dans `tiers_helpers.py`) concerne les TIERS, pas les TITRES.

**Fix applique** : VP-E est **repositionne en pur refactor `plan_support.py`** (decoupe haute LOC). Branche canonical SUPPRIMEE. L'effort passe de **14h a 10h** (suppression du module `domain/canonical.py` initialement prevu). Si un concept "canonical title" est juge utile en V2, il sera trace dans une vague ulterieure avec inventaire prealable des call-sites concrets.

### Fix #2 - VP-D save_validation : cablage explicite

**Critique** : `grep save_validation cinesort/ui/api/library_support.py` retourne 0 match. Le brief original cible `library_support.py` mais l'architecture actuelle ne stocke pas les decisions a cet endroit.

**Fix applique** : VP-D **cable explicitement via** `cinesort_api._save_validation_impl` + `run_flow_support.save_validation` + `run_facade.save_validation`. La nouvelle table `film_decisions_v2` est lue/ecrite par un nouveau `cinesort/infra/db/repositories/decisions.py` (pas dans `library.py` qui n'existe pas non plus). L'UI `lib-validation.js` appelle l'endpoint via le facade existant, pas via une nouvelle route library.

### Fix #3 - VP-G open question "v5+legacy"

**Critique** : statut v5/legacy actuel ambigu.

**Fix applique** : VP-G **inclut un audit prealable 1h** des overlays mutuels v5 vs legacy avant cablage des 3 features (VP-A badge / VP-C cadenas / VP-D boutons tri-etat). Si conflit detecte, fallback strict legacy-first conformement memo `feedback_cinesort_v76_ui`.

### Fix #4 - VP-B preset par defaut TRaSH 2026

**Critique** : risque de deplacement 30-40% tiers sur biblio 853 films si preset embarque par defaut.

**Fix applique** : preset `tier_preset_trash_2026.json` **embarque mais DESACTIVE par defaut** (toggle OFF, opt-in explicite via UI parametres). Sur nouvelles installations : toggle propose en assistant initial mais default OFF preserve. Documentation UI : "Activer le mode TRaSH 2026 peut redistribuer 30-40% de votre biblioteque actuelle - consultez la simulation avant d'activer".

### Fix #5 - VP-C strategie cle stable film_id (passage path: -> tmdb:)

**Critique** : que faire des locks existants quand un film passe de `path:<sha1>` a `tmdb:<id>` apres Identify manuel ?

**Fix applique** : strategie **MIGRATE locks** lors de la transition. La table `film_field_locks` ajoute un index `idx_film_id` et une fonction `migrate_locks(old_film_id, new_film_id)` exposee par `field_locks.py` repository. Appelee dans `_rematch_tmdb_and_update_plan` lors de la transition path: -> tmdb:. Test dedie : `test_field_locks_migration_path_to_tmdb.py`.

---

## 3. Tableau des sub-lots

| lot_id | Titre | Items | Heures reelles | Depends_on |
|--------|-------|-------|----------------|------------|
| **VP-A** | Fondations transactionnelles & migration 029 - apply_atomic forward rollback | 1 | 15 | - |
| **VP-B** | Hierarchie qualite tier-trumps & scoring multi-axes (inspire TRaSH/Radarr) | 1 | 10 | - |
| **VP-C** | Field locks Jellyfin-style & merge_metadata (migration 030) | 1 | 15 | - |
| **VP-D** | Decisions tri-etat & save_validation (migration 031, backward compat `ok:bool` ABSOLUE) | 1 | 12 | VP-A, VP-C |
| **VP-E** | Refactor `plan_support.py` decoupe haute LOC (canonical SUPPRIME apres fix #1) | 1 | **10** (revise, ex 14) | - |
| **VP-F** | Quality profiles facade & UI parametres (TRaSH-compatible) | 1 | 11 | VP-B |
| **VP-G** | Audit complementaire & integration finale UI library | 1 | **10** (incl. +1h audit v5+legacy fix #3) | VP-C, VP-D |
| **SOUS-TOTAL items** | | **7** | **103h reel** | |
| **Buffer integration 25%** | docs / tests croises / smoke E2E / regression visuelle tier colors | - | **+25.75h** | - |
| **TOTAL ceiling annonce** | | **7** | **128.75h** | |

**Arithmetique** : 15 + 10 + 15 + 12 + 10 + 11 + 10 = **103h reel**. Buffer 25% (25.75h) couvre :
- Tests d'integration croises VP-A/C/D (apply_atomic + field_locks + tri-etat coexistent sans casser `{ok:bool}`).
- Smoke E2E scenario complet "identify -> lock -> rescan -> apply_atomic avec tri-etat deferred".
- Regression visuelle tier colors (tokens.css INVARIANT verifie).
- Documentation interne par sub-lot + mise a jour `CLAUDE.md` + `BILAN_PHASES.md`.

**Decoupe alternative possible** (open question #8 plan) : P1 = VP-A/B/C autonomes (~50h) + P2 = VP-D/E/F/G dependants (~53h). **Decision : Vague P unifiee** (128.75h ceiling) pour garantir coherence end-to-end et eviter regression entre P1 et P2 sur 853 films biblio reelle.

---

## 4. Items detailles par sub-lot

### VP-A - Apply atomique forward rollback - 15h

#### Item VP-1-APPLY-ATOMIC

**Backend**
- Flag `apply_atomic=True` kwarg **OPT-IN** strict (default False) - backward compat ABSOLUE shape `{ok:bool}` preservee.
- Migration `029_apply_atomic_mode.sql` : `CREATE TABLE apply_batch_modes(batch_id PK FK, atomic_enabled INT, rollback_status TEXT, rolled_back_at TEXT)` -> `CREATE INDEX idx_apply_batch_modes_status` -> `PRAGMA user_version=29`. PAS d'ALTER (memo SQLite). Testee fixture `test_existing_db_fixture_v77` cas v28->v29.
- Etendre `cinesort/infra/db/repositories/apply.py` : `upsert_atomic_mode(batch_id, enabled)`, `mark_rollback_status(batch_id, status)`.
- Nouveau module `cinesort/app/apply_rollback.py` : `rollback_forward(batch_id)` = reverse-undo sur suffixe journalise (move_journal existant). Utilise `connect(autocommit=False)` PEP 249 pour rollback FS+DB coordonne (pattern SQLite 2026).
- Cablage : `apply_support._validate_apply` + `_execute_apply` + `cinesort_api._apply_impl` + `run_facade.apply` (4 points).
- Coordination undo classique : `rollback_status='ROLLED_BACK_BY_ATOMIC'` SEPARE de l'undo_status existant (fix open question VP-A) - `get_last_reversible_apply_batch` non impacte.

**UI**
- `web/dashboard/views/traitement.js` : toggle `apply_atomic` avec `dangerConfirmModal` listant consequences ("Tous les renommages de ce batch seront annules en cas d'erreur sur l'un d'eux"). Pas de countdown 3s (action conditionnelle non-suppression, memo `feedback_cinesort_actions_dangereuses` autorise countdown OFF quand non-destructif).
- Badge "Mode atomique" visible dans historique batches.
- `node --check traitement.js` obligatoire avant release + F12 console verifiee.

**Tests**
- `tests/test_apply_atomic_mode.py` (8-10 unitaires : flag opt-in, rollback FS+DB, coexistence undo).
- Extension `test_existing_db_fixture_v77.py` cas v28->v29.
- Test integration : rollback partiel (5 sur 10 deplacements echouent -> tous annules).

**Acceptance criteria**
- AC-1 : default OFF, signature `apply()` retourne TOUJOURS `{ok:bool}` (backward compat).
- AC-2 : migration 029 idempotente (re-run safe), fixture v28 reelle testee.
- AC-3 : rollback FS+DB atomique - si DB rollback echoue, FS revert tente avec log d'audit.
- AC-4 : `dangerConfirmModal` toggle UI affiche consequences sans countdown.
- AC-5 : 0 regression sur tests undo existants (`test_apply_undo_*`).

---

### VP-B - Hierarchie qualite tier-trumps - 10h

#### Item VP-2-HIERARCHIE-TIER

**Backend**
- Nouveau `cinesort/domain/tiers_helpers.py:apply_tier_hierarchy(tier_pondere, dimensions, hierarchy_config)` (greffe AVANT `cap_tier` existant).
- Tier floors/ceilings par dimension : **resolution** (2160p_probe -> Gold floor, 720p -> Silver ceiling) > **video_codec** (AV1/HEVC -> Gold floor possible) > **HDR** (DV/HDR10+ -> Gold floor) > **audio** (TrueHD Atmos -> Gold floor) > **release_group** (scene tier groups).
- Ordre execution : `custom_rules force_tier` > `apply_tier_hierarchy` > `_cap_tier` securite (FAILED -> Silver, CAM -> Bronze restent autorite finale).
- `default_quality_profile` + `validate_quality_profile` etendus avec cle `tier_hierarchy = {enabled, order, resolution_floors, codec_floors, hdr_floors, audio_floors, group_floors}`.
- **Toggle DEFAULT FALSE en V1** (opt-in, zero surprise sur 853 films biblio) - fix #4 applique.
- **PAS de migration SQL** (profile_json suffit).

**UI**
- `web/dashboard/views/parametres.js` : section "Hierarchie qualite" (toggle + reorder 5 dimensions par drag-and-drop).
- Documentation in-app : "Activer ce mode peut redistribuer 30-40% de votre biblioteque actuelle - utilisez la simulation avant d'activer" (fix #4).
- `node --check parametres.js` obligatoire avant release.

**Tests**
- `tests/test_tier_hierarchy_floors.py` (12-15 unitaires : floors par dimension, ordre execution, interaction `_cap_tier`).
- `tests/test_quality_score_hierarchy_integration.py` (6-8 integration avec scoring V1 reel).
- `tests/test_tier_hierarchy_profile_migration.py` (legacy profil sans cle `tier_hierarchy` -> default OFF).

**Acceptance criteria**
- AC-1 : default OFF, scoring V1 inchange si toggle non active.
- AC-2 : `_cap_tier` securite (FAILED/CAM) reste autorite finale meme avec hierarchy ON.
- AC-3 : `composite_score_v2` perceptual **NON modifie** (memo `perceptual_reports != quality_reports`).
- AC-4 : **tier colors hex INVARIANTES** (tokens.css NON touche).
- AC-5 : import-linter green (`domain/` ne depend ni de `app/` ni de `infra/` ni de `ui/`).

---

### VP-C - Field locks Jellyfin-style - 15h

#### Item VP-3-FIELD-LOCKING

**Backend**
- Migration `030_field_locks.sql` : `CREATE TABLE film_field_locks(id PK, film_id, run_id, row_id, field_name, locked_value, locked_at, source) UNIQUE(film_id, field_name)` -> `CREATE INDEX idx_film, idx_field, idx_film_id` -> `PRAGMA user_version=30`. PAS d'ALTER.
- Cle stable `film_id` = `tmdb:<id>` OU `path:<sha1(folder+video)>` via nouveau `cinesort/domain/film_identity.py:compute_film_id(row)`.
- Nouveau `cinesort/infra/db/repositories/field_locks.py` : `set_lock`, `clear_lock`, `get_lock`, `is_locked`, `list_locks`, **`migrate_locks(old_film_id, new_film_id)`** (fix #5).
- Couche `cinesort/app/merge_metadata.py:merge_metadata(source, target, locked_fields, replace_data)` calquee sur Jellyfin `MergeData` : tout enrichissement OMDb/TMDb/rescan passe par cette barriere.
- Backward compat `film_tmdb_overrides` preservee (pas d'ALTER, table parallele coexiste).
- Integration : `library_actions_support._rematch_tmdb_and_update_plan` (L239) + `_rescan_single_row_full_pipeline` (L182) consultent les locks avant ecrasement. Lors transition path: -> tmdb: : appel `migrate_locks` (fix #5).

**UI**
- `web/dashboard/views/library/lib-validation.js` : cadenas par champ + indicateur visuel verrouille + auto-lock apres "Identify manuel" (workflow Jellyfin).
- 2 modes UI : "Completer les manques uniquement" (defaut) vs "Tout reconstruire" (`dangerConfirmModal` OBLIGATOIRE avec liste champs + countdown 3s si >50 items, memo actions dangereuses).
- `node --check lib-validation.js` obligatoire avant release.

**Tests**
- `tests/test_field_locks_persistence.py` : persistance via close/reopen connexion SQLite (lecon bug Jellyfin #15549).
- `tests/test_merge_metadata_resistance_rescan.py` : OMDb/TMDb refresh respecte les locks.
- `tests/test_field_locks_migration_path_to_tmdb.py` : migration locks lors Identify manuel (fix #5).
- Extension `test_existing_db_fixture_v77.py` cas v29->v30.

**Acceptance criteria**
- AC-1 : migration 030 testee fixture v29 reelle (post-VP-A).
- AC-2 : champ verrouille resiste a `_rescan_single_row_full_pipeline` complet.
- AC-3 : transition film path: -> tmdb: migre TOUS les locks de l'ancien film_id.
- AC-4 : `film_tmdb_overrides` coexiste (zero regression).
- AC-5 : `dangerConfirmModal` mode "Tout reconstruire" avec countdown 3s si >50 items.

---

### VP-D - Decisions tri-etat & save_validation - 12h

#### Item VP-5-TRI-ETAT-DECISIONS

**Backend**
- Migration `031_tri_etat_decisions.sql` : `CREATE TABLE film_decisions_v2(id PK, film_id, run_id, decision TEXT CHECK(decision IN ('accepted','rejected','deferred')), decided_at, decided_by, reason)` -> `CREATE INDEX idx_film_decision, idx_run_decision` -> `PRAGMA user_version=31`. PAS d'ALTER.
- Nouveau `cinesort/infra/db/repositories/decisions.py` (fix #2 - pas dans `library.py` qui n'existe pas).
- **Backward compat ABSOLUE** : helper `to_legacy_ok_bool(decision) = (decision == 'accepted')`. Tous les endpoints existants qui retournent `{ok: bool}` conservent leur shape via ce helper.
- **Cablage explicite via** (fix #2) :
  - `cinesort_api._save_validation_impl` (point d'entree API)
  - `run_flow_support.save_validation` (orchestration flux)
  - `run_facade.save_validation` (facade UI)
- Coordination merge avec **VP-A** : `apply_atomic` kwargs distincts pour eviter conflits sur `_validate_apply`/`_apply_changes_body`.
- Coordination **VP-C** : `field_locks` consultes lors transition `deferred -> accepted` pour respecter overrides.

**UI**
- `web/dashboard/views/library/lib-validation.js` : 3 boutons (Accepter / Rejeter / Reporter) avec `dangerConfirmModal` sur "Rejeter" si >50 items (countdown 3s, memo actions dangereuses).
- Badge "Reporte" persistant cote UI + filtre par etat.
- `node --check lib-validation.js` obligatoire avant release.

**Tests**
- `tests/test_tri_etat_decisions.py` : transitions etats (accepted <-> rejected <-> deferred), backward compat legacy `ok:bool`, interactions avec `apply_atomic` + `field_locks`.
- `tests/test_save_validation_backward_compat.py` : tous les endpoints existants retournent toujours `{ok:bool}` sur appels legacy.
- Extension `test_existing_db_fixture_v77.py` cas v30->v31.

**Acceptance criteria**
- AC-1 : migration 031 testee fixture v30 reelle (post-VP-C).
- AC-2 : signature API `save_validation()` retourne `{ok:bool}` sur appel legacy (helper transparent).
- AC-3 : transition `deferred -> accepted` respecte les `field_locks` de VP-C.
- AC-4 : `dangerConfirmModal` "Rejeter >50 items" avec countdown 3s.
- AC-5 : coexistence apply_atomic (VP-A) sans collision kwargs.

---

### VP-E - Refactor `plan_support.py` (canonical SUPPRIME) - 10h

#### Item VP-6-PLAN-SUPPORT-DECOUPE

**Fix #1 applique** : la branche "canonical" est SUPPRIMEE de ce lot. VP-E devient un **pur refactor de decoupe `plan_support.py`** (2715 LOC) en sous-modules thematiques.

**Backend**
- Decoupe `cinesort/app/plan_support.py` (2715 LOC, fichier MAJEUR) en sous-modules :
  - `cinesort/app/plan_support_core.py` (orchestration principale, ~900 LOC cible).
  - `cinesort/app/plan_support_replan.py` (logique replan/refresh, ~600 LOC cible).
  - `cinesort/app/plan_support_dedup.py` (deduplication intra-plan, ~500 LOC cible).
  - `plan_support.py` conserve un facade-re-export pour backward compat des imports existants (~200 LOC).
- Respect import-linter : tous restent dans `app/`, aucune cross-dep vers `domain/` non autorisee.
- **PAS de modification de la semantique** des titres au-dela du renommage configure (memo user inviolable).
- **PAS de nouveau module `domain/canonical.py`** (fix #1 - aucun call-site reel).

**UI**
- Aucun changement UI (refactor pur backend).

**Tests**
- Extension `tests/test_plan_support_modules.py` : verifier 0 regression sur fixtures existantes (smoke 853 films).
- `tests/test_plan_support_facade_reexports.py` : tous les imports legacy `from cinesort.app.plan_support import X` continuent de fonctionner.

**Acceptance criteria**
- AC-1 : LOC `plan_support_core.py` < 1000, `plan_support_replan.py` < 700, `plan_support_dedup.py` < 600.
- AC-2 : 0 regression sur smoke 853 films (jeu de test reel).
- AC-3 : import-linter green.
- AC-4 : facade `plan_support.py` re-export complete (tous symboles publics).
- AC-5 : pas de fonction renommee "canonical" introduite sans inventaire prealable des call-sites.

---

### VP-F - Quality profiles facade & UI parametres - 11h

#### Item VP-7-QUALITY-PROFILES

**Backend**
- **Extension** de `quality_facade.py` existant (328 LOC) PLUTOT que nouvelle facade (recommandation critique). Decoupe `profiles_support.py` (421 LOC) en sous-modules `profiles_support_crud.py` + `profiles_support_import_export.py`.
- Endpoints CRUD profils + import/export YAML compatible Recyclarr (pattern web TRaSH 2026).
- Embarquer preset `tier_preset_trash_2026.json` (DESACTIVE par defaut, fix #4) + presets alternatifs (puriste DV, qualite max audio).
- Integration toggle `tier_hierarchy` de VP-B via facade etendue.
- Champ `upgrade_until_score` (default 10000) pour reduire bruit decisionnel.

**UI**
- `web/dashboard/views/parametres.js` : section "Profils qualite" avec import/export, breakdown 5 axes (Source/Codec/HDR/Audio/Group) pour transparence scoring (memo `feedback_cinesort_ui_pacotille` : eviter fonctions invisibles).
- `node --check parametres.js` obligatoire avant release.

**Tests**
- `tests/test_quality_profiles_facade_extension.py` (extension, pas nouvelle facade).
- `tests/test_recyclarr_import_export.py` (round-trip YAML).
- `tests/test_quality_facade_backward_compat.py` (signatures existantes preservees).

**Acceptance criteria**
- AC-1 : `quality_facade.py` etendue (pas dupliquee), `profiles_support.py` decoupe sans regression.
- AC-2 : import/export Recyclarr YAML round-trip lossless.
- AC-3 : preset TRaSH 2026 embarque mais DESACTIVE par defaut (fix #4).
- AC-4 : breakdown 5 axes affiche dans UI.
- AC-5 : `upgrade_until_score` exposable via UI (default 10000).

---

### VP-G - Audit complementaire & integration finale UI library - 10h

#### Item VP-4-LIBRARY-UI-INTEGRATION

**Audit prealable** (fix #3, +1h) :
- Inventaire des overlays mutuels `lib-validation.js` v5 vs legacy (statut ambigu post-Vague O).
- Si conflit detecte : fallback strict legacy-first (memo `feedback_cinesort_v76_ui`).

**Backend**
- Aucun nouveau backend - cablage end-to-end des features VP-A/C/D existantes.

**UI**
- `web/dashboard/views/library/lib-validation.js` : cablage end-to-end :
  - Affichage cadenas `field_locks` (VP-C).
  - Boutons tri-etat accepted/rejected/deferred (VP-D).
  - Badge `apply_atomic` mode (VP-A).
- Respect memo `feedback_cinesort_v76_ui` : overlays mutuels, coexistence v5+legacy, endpoints dans `library_support.py` (pas de fuite vers controllers).
- Notifications independantes du toast OS.
- **Tier colors hex INVARIANTES** respectees dans tous nouveaux composants (tokens `--tier-*` reutilises, tokens.css NON touche).

**Tests E2E**
- Scenario complet : `identify -> lock champ titre -> rescan TMDb -> apply_atomic avec tri-etat deferred`.
- Audit memo actions dangereuses : toute action destructive UI library (suppression lock, reset decision, "Tout reconstruire") demande `dangerConfirmModal` avec liste + countdown 3s si >50.

**Acceptance criteria**
- AC-1 : audit v5+legacy documente avant cablage (fix #3).
- AC-2 : scenario E2E green sur biblio reelle (853 films).
- AC-3 : `node --check lib-validation.js` + F12 console verifiees (memo `js_release_checks`).
- AC-4 : tier colors hex INVARIANTES (regression visuelle verifiee).
- AC-5 : zero action destructive UI library sans `dangerConfirmModal`.

---

## 5. Convergences deep + logic + web research

### 5.1 Convergence SQLite 2026 (recherche `sqlite_transactions`)
- **Pattern PEP 249** : `connect(autocommit=False)` adopte dans VP-A pour rollback FS+DB coordonne (recommandation 2026 SQLite).
- **Migrations ordonnees** : 029 (VP-A `apply_batch_modes`) -> 030 (VP-C `film_field_locks`) -> 031 (VP-D `film_decisions_v2`). Toutes en **CREATE TABLE -> CREATE INDEX strict**, PAS d'ALTER (memo `feedback_sqlite_migration_test_existing_db`).
- **Fixture v77 etendue** : chaque migration testee avec base PRE-EXISTANTE (v28->v29, v29->v30, v30->v31).

### 5.2 Convergence TRaSH/Radarr 2026 (recherche `radarr_quality_tiers`)
- **"Quality Trumps All"** : hierarchie multi-axes (Source > Codec > HDR > Audio > Group) implementee dans VP-B `apply_tier_hierarchy`.
- **Custom Format Groups** : preset `tier_preset_trash_2026.json` embarque (scores 1950-1600 source, 5000-750 audio) DESACTIVE par defaut (fix #4).
- **Recyclarr YAML** : import/export compatible via VP-F.

### 5.3 Convergence Jellyfin LockedFields 2026 (recherche `jellyfin_lock_fields`)
- **Verrous champ-par-champ** : VP-C reproduit le pattern Jellyfin `LockedFields` avec table dediee `film_field_locks`.
- **merge_metadata** : barriere `cinesort/app/merge_metadata.py` calquee sur `MergeData` Jellyfin.
- **Lecon bug Jellyfin #15549** : test persistance lock via close/reopen connexion SQLite (verif que les locks survivent au refresh).

### 5.4 Convergence backward compat ABSOLUE
- VP-A : `apply_atomic` kwarg OPT-IN default False.
- VP-B : toggle `tier_hierarchy` DEFAULT FALSE.
- VP-D : helper `to_legacy_ok_bool()` preserve shape `{ok:bool}` sur TOUS endpoints existants.
- VP-F : extension `quality_facade.py` (pas nouvelle facade, pas de duplication).
- **Aucune signature API ne casse**.

### 5.5 Convergence tier colors hex INVARIANTES
- VP-B agit sur seuils/logique, **PAS** sur tokens.
- VP-G nouveaux composants reutilisent `--tier-*` tokens existants.
- `tokens.css` strictement NON touche dans toute la Vague P.
- Regression visuelle verifiee dans buffer integration.

### 5.6 Convergence dangerConfirmModal systematique
- VP-A : toggle `apply_atomic` avec consequences listees (countdown OFF car non-destructif).
- VP-C : mode "Tout reconstruire" avec countdown 3s si >50 items.
- VP-D : "Rejeter" avec countdown 3s si >50 items.
- VP-G : audit toutes actions UI library (suppression lock, reset decision).

### 5.7 Convergence architecture import-linter
- VP-B : nouveau code dans `domain/tiers_helpers.py` (zero dependance vers `app`/`infra`/`ui`).
- VP-C : repository dans `infra/db/`, `film_identity` dans `domain/`, `merge_metadata` dans `app/`.
- VP-E : decoupe `plan_support.py` reste dans `app/` (pas de cross-dep vers `domain/`).
- VP-F : facade etendue dans `ui/api/facades/`, support dans `ui/api/`.

### 5.8 Convergence perceptual != quality
- VP-B touche **QUE** `quality_score` V1.
- `composite_score_v2` (perceptual, 766 LOC) **NON modifie**.
- Memo `feedback_cinesort_design` strictement respecte.

### 5.9 Convergence subprocess direct
- ffprobe/mediainfo subprocess direct **non impacte** par aucun sub-lot.
- Memo `feedback_cinesort_design` respecte.

### 5.10 Convergence node --check + F12 console
- `traitement.js` (VP-A) : verification obligatoire.
- `parametres.js` (VP-B + VP-F) : verification obligatoire.
- `lib-validation.js` (VP-C + VP-D + VP-G) : verification obligatoire.
- Memo `feedback_js_release_checks` respecte.

### 5.11 Convergence titres inviolables
- VP-E ne modifie PAS la semantique des titres (refactor pur).
- Branche canonical SUPPRIMEE (fix #1).
- Memo user inviolable respecte.

---

## 6. Plan d'execution suggere

**Ordre recommande** (en parallele quand possible, sub-agents en worktrees isoles - memo `feedback_multi_agents_parallel`) :

1. **Phase 1** (parallele) : VP-A + VP-B + VP-E (aucune dependance).
2. **Phase 2** (parallele) : VP-C (depend de rien) + VP-F (depend de VP-B termine).
3. **Phase 3** : VP-D (depend de VP-A + VP-C termines).
4. **Phase 4** : VP-G (depend de VP-A + VP-C + VP-D termines) - integration finale + audit v5+legacy.
5. **Phase 5** : buffer integration (tests croises, smoke E2E, regression visuelle, docs).

**Fin de phase** : MAJ obligatoire `CLAUDE.md` + `BILAN_PHASES.md` (memo `feedback_update_claude_md`).

---

## 7. Open questions resolues post-fixes

| # | Question | Resolution |
|---|----------|------------|
| 1 | VP-D save_validation cablage | **FIX #2** : `cinesort_api` + `run_flow_support` + `run_facade` + nouveau `repositories/decisions.py`. PAS dans `library_support.py`. |
| 2 | VP-E plan_support.py perimetre | **FIX #1** : refactor pur decoupe (10h), canonical SUPPRIME. |
| 3 | VP-F quality_profiles facade | **Recommandation critique adoptee** : extension `quality_facade.py` existant + decoupe `profiles_support.py`. Pas de nouvelle facade. |
| 4 | VP-C film_id transition path: -> tmdb: | **FIX #5** : `migrate_locks(old_film_id, new_film_id)` appele dans `_rematch_tmdb_and_update_plan`. |
| 5 | VP-A interaction undo_status | **Resolu** : `rollback_status='ROLLED_BACK_BY_ATOMIC'` SEPARE dans `apply_batch_modes`, undo classique non impacte. |
| 6 | VP-B preset par defaut | **FIX #4** : preset TRaSH 2026 embarque mais DESACTIVE par defaut, opt-in assistant initial. |
| 7 | VP-G coexistence v5+legacy | **FIX #3** : audit prealable 1h inclus dans le lot. |
| 8 | Decoupe P1/P2 vs Vague unifiee | **Decision** : Vague P unifiee (128.75h ceiling) pour coherence end-to-end. |

---

## 8. 🎁 Pour toi

**Vague P concerne la solidite et le controle** : applique transactionnel rollback-able, hierarchie qualite plus juste (4K HDR bat 720p toujours), verrouillage des corrections manuelles (comme Jellyfin lock fields), protection contre les modifications concurrentes (HTTP 409), tags providers pour identifications deterministes, double seuils de qualite style Radarr.

Concretement, apres cette vague :
- Quand tu appliques un batch de renommages, si quelque chose foire au milieu, **tout** est annule (pas seulement le dernier fichier) - tu retrouves ta biblio exactement dans l'etat d'avant.
- Quand tu corriges manuellement un titre ou une annee d'un film, **le rescan TMDb ne l'ecrase plus jamais** (comme dans Jellyfin avec ses cadenas par champ).
- Quand tu hesites sur un film, tu peux maintenant le **"Reporter"** au lieu d'etre force de choisir "Accepter ou Rejeter" - et tu y reviendras plus tard tranquillement.
- Le classement qualite devient plus intuitif : un **4K HDR Dolby Vision battra toujours un 720p**, peu importe les autres criteres - fini les surprises ou un encodage exotique en 720p remontait au-dessus d'un 4K propre.
- Tu peux **importer/exporter tes profils qualite** en YAML compatible avec la communaute TRaSH-Guides (la reference Radarr/Sonarr).

**Tout est en opt-in** : par defaut, rien ne change dans ton comportement actuel. Tu actives les nouveautes quand tu veux, comme tu veux. Et tes 853 films biblio ne bougeront pas d'un pouce sans que tu valides explicitement.

---

## 9. Tag mini-recovery

A la fin de l'application de cette roadmap, le tag `mini-recovery-p` sera pose avec message :

```
Mini-recovery Vague P: plan sub-lots + audits + web research (GO_WITH_FIXES)
```

Pas de bump VERSION (mini-recovery, pas release). Pas de push remote (memo session).
