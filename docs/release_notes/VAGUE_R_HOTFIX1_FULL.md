# Hotfix1 Full - 10 critical + 15 high (post bug hunt ultra)

## Pour toi

Une revue exhaustive de 90+ bugs trouves apres les 6 vagues. On a fixe les 10 critiques (dont une cascade silencieuse sur la base de donnees, des cas de pertes de decisions sur la validation tri-etat, des crashes sur films francais et plusieurs faux comportements de scoring) et 15 hauts. L app est maintenant prete pour test reel sur ta biblio.

## Build

- EXE: 53.71 MB
- Smoke: starts=true, startup=5.82s, health=true

## Fixes appliques par fichier

### `cinesort/infra/db/sqlite_store.py` (BUG-001, BUG-002 - critical x2)

- **BUG-001 [CRITICAL]**: `_bootstrap_schema_latest` concatenait toutes les migrations y compris la 025 (`@manager: disable_fk`). Sans desactivation des FK avant BEGIN, le `DROP TABLE runs` cascade-supprimait silencieusement `errors`, `quality_reports`, `anomalies`. Detection du marker dans le script global + `PRAGMA foreign_keys=OFF` avant la transaction + restauration en `finally`.
- **BUG-002 [CRITICAL]**: `REQUIRED_SCHEMA_TABLES` omettait `apply_batch_modes` (mig 029), `film_field_locks` (mig 030), `film_decisions_v2` (mig 031). Le filet self-healing `_ensure_required_schema` ne se declenchait jamais pour ces tables. Ajout des 3 tables dans le tuple.

### `cinesort/domain/probe_models.py` (helpers centralises pour BUG-008/BUG-018)

- Ajout `probe_quality_is_failed` et `probe_quality_is_partial_or_failed` (tolere casse mixte, espaces, None).
- Ajout champs `edition` et `tmdb_collection_id` au dataclass `NormalizedProbe` (BUG-008).

### `cinesort/domain/quality_score.py` (BUG-010, BUG-019, BUG-021 - critical+high x2)

- **BUG-010 [CRITICAL]**: `_compute_confidence_helper` lisait `vr[width]`, `vr[height]`, `vr[video_codec]`, `vr[bitrate_kbps]`, `vr[resolution_source]` sans `.get` -> KeyError silencieux qui bypassait la confidence. `.get(key, default)` defensif partout, avec `_to_int(.., 0)` pour width/height.
- **BUG-019 [HIGH]**: `probe.get(probe_quality) or "FAILED"` ecrasait tout cas non valide en FAILED -> cap Silver injuste. Differencier 'champ absent' (-> "UNKNOWN", pas de cap_tier) vs 'valeur vide/invalide' (-> FAILED + warning).
- **BUG-021 [HIGH]**: `_codec_bonus` lisait `profile[codec_bonuses][av1_bonus]` direct sans `.get` -> KeyError silencieux si profil partiel. `profile.get(codec_bonuses) or {}` + `_to_int(bonuses.get(key), 0)` pour chaque codec.

### `cinesort/app/apply_core.py` + `cinesort/app/plugin_hooks.py` (BUG-009 - critical)

- **BUG-009 [CRITICAL]**: Deux silent failures autour du `row_id`, absorbees par le catch global comme `SKIP_REASON_ERREUR_PRECEDENTE`.
  1. `move_duplicate_losers_to_user_decided`: `by_row` dict construit avec `if getattr(r, "row_id", None)` ignorait silencieusement les PlanRows dont `row_id` etait vide/0. Log WARN explicite `DUPLICATE_LOSER` desormais.
  2. `apply_rows` main loop: `int(dec.get("year") or row.proposed_year)` crashait `TypeError`/`ValueError` sur year non-numerique ("", "????", "abc") ou `proposed_year` None. Fallback `or 0`, `try/except` local, WARN `YEAR_CAST` avec valeur exacte.

### `cinesort/ui/api/run_flow_support.py` (BUG-003, BUG-004, BUG-011 - critical x2 + high)

- **BUG-003/BUG-004 [CRITICAL VP-D]**: `save_validation` acceptait `decision=deferred` mais `validation.json` conservait `ok=true` et le mirror SQL voyait `ok=None`. Nouveau helper `_project_decisions_ok_from_tri_state` applique `to_legacy_ok_bool(decision)` AVANT `_normalize_decisions_for_rows` et avant `_mirror_decisions_to_sql` -> coherence JSON <-> SQL.
- **BUG-011 [HIGH]**: Double-click UI sur "Enregistrer validation" causait un last-write-wins. Verrou `threading.Lock` par `run_id` via lazy init de `api._save_validation_locks` (backward compat absolue).

### `cinesort/infra/db/migration_manager.py` (BUG-013, BUG-014, BUG-015 - critical+high x2)

- **BUG-013 [CRITICAL]**: `_record_migration` catche maintenant `sqlite3.Error` (parent de `OperationalError`) et logue un warning au lieu d'un silent pass. Failures schema_migrations diagnostiquables.
- **BUG-014 [HIGH]**: Marker `@manager: disable_fk` detecte via match strict ligne par ligne (`line.strip().startswith("-- @manager: disable_fk")`) au lieu de `"in sql"` substring -> commentaires descriptifs ne peuvent plus toggler `PRAGMA foreign_keys = OFF` par accident.
- **BUG-015 [HIGH]**: `_split_sql_statements` refuse explicitement `/* ... */` block comments (fallback sqlparse) et ignore `;` dans string literals (`'...'` avec `''` escape) au lieu d'un split malforme.

### `cinesort/ui/api/run_control_support.py` (BUG-012 - high)

- **BUG-012 [HIGH]**: `_pause_or_save` inverse l'ordre signaling/DB pour eviter incoherence ou `pause_event` etait pose avant `mark_run_paused`. Persistance DB d'abord, signaling JobRunner ensuite, symetrique a `resume_run`.

### `cinesort/ui/api/perceptual_support.py` (BUG-005 - critical, BUG-018 callsite)

- **BUG-005 [CRITICAL]**: `_run_perceptual_job` worker - catch trop etroit `(OSError, KeyError, TypeError, ValueError)`. Si `compare_perceptual` levait autre chose (RuntimeError, AttributeError, ImportError), la boucle remontait sans snapshot final `status=done` + `ts_end`, laissant le job en `running` indefiniment cote polling. Wrap `try/except Exception` large avec finalisation `status="error"` + `ts_end` + message. `_trim_perceptual_jobs` deplace en `finally`.
- **BUG-018 callsite**: utilise `probe_quality_is_failed` au lieu de `==FAILED` case-sensitive.

### `cinesort/ui/api/dashboard_support.py` + `cinesort/ui/api/quality_report_support.py` + `cinesort/ui/api/library_support.py` (BUG-018 - high)

- **BUG-018 [HIGH]**: `probe_quality` comparait strict `==FAILED` case-sensitive dans certains consommateurs UI alors que `dashboard_support` utilisait `.upper()`. Divergence silencieuse qui masquait des etats FAILED selon le consommateur. Helpers centralises `probe_quality_is_failed` / `probe_quality_is_partial_or_failed` utilises dans les 3 callsites UI. Tolere casse mixte, espaces, None.

## Commits inclus

- `5c61e11` fix(hotfix1): perceptual_support - BUG-005 - critical
- `d440192` fix(hotfix1): run_control_support - BUG-012 - high
- `0158c2a` fix(hotfix1): migration_manager - BUG-013,BUG-014,BUG-015 - critical+high
- `30a7b92` fix(hotfix1): sqlite_store - BUG-001,BUG-002 - critical+critical
- `e215bc0` fix(hotfix1): run_flow_support - BUG-003,BUG-004,BUG-011 - critical+high
- `df0619a` fix(hotfix1): apply_core - BUG-009 - critical
- `d9589bd` fix(hotfix1): quality_score - BUG-010,BUG-019,BUG-021 - critical+high
- `672bbe0` fix(hotfix1): library_support - BUG-018 - high

## Tag

`vague-r-hotfix1-full` (local, pas de push remote)
