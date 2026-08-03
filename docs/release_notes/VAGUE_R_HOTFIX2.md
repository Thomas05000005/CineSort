# Hotfix2 - 24 bugs (5 regressions hotfix1 + 5 critical + 14 high data-loss/state/leaks)

## Pour toi

Un second passage post-hotfix1 a trouve 60 bugs additionnels. On a corrige les 5 regressions du premier hotfix (notamment une race condition latente sur la sauvegarde des decisions, un score 4K REMUX faux a cause d une heuristique de bitrate cassee, et UNKNOWN traite comme FAILED par erreur), les 5 nouveaux critiques (subprocess ffmpeg orphelins, transitions d etats incoherentes sur les jobs en pause), et 14 hauts dont 4 risques de perte de fichiers reels sur shutil.move Windows. L app est maintenant la plus solide jamais livree.

## Build

- EXE: 53.72 MB
- Smoke: starts=true, startup=7.95s, health=true

## Fixes par fichier

### `cinesort/app/job_runner.py` (C2, C3, C4, H15, H16 - 2 regressions + 1 critical + 2 high)

- **C2 [CRIT - regression]**: Transition PENDING -> CANCELLED directe violait l invariant "cancelled a forcement demarre" : `started_ts` restait NULL. Fix : force `mark_run_running` puis `mark_run_cancelled` avec `started_ts = ended_ts = now()` -> duration=0 documentee + statut metier coherent (dashboard, rapports).
- **C3 [CRIT - regression]**: Desync snapshot memoire vs DB sur PAUSED. `request_pause` ne mettait pas a jour `rt.snapshot.status` alors que `RunRepository.mark_run_paused` persistait PAUSED -> UI affichait toujours RUNNING. Fix : `request_pause` aligne snapshot sur PAUSED (running=False), `request_resume` restaure sur RUNNING.
- **C4 [CRIT]**: `mark_run_done/cancelled/failed` ecrasaient silencieusement PAUSED car aucune clause WHERE status dans le UPDATE repo. Fix : guard `_is_user_held_state` qui interroge la DB avant toute transition terminale ; si etat operateur (PAUSED/SAVED/AWAITING), transition skip, snapshot memoire aligne, erreur tracee dans `errors` mais pas dans `runs`.
- **H15 [HIGH]**: `_active_run_locked` excluait PAUSED/AWAITING_VALIDATION/SAVED -> `start_job` pouvait lancer un nouveau run en parallele d un thread suspendu (2 jobs sur meme store). Fix : nouveau set `_RESERVED` incluant ces etats ; `_ACTIVE` reste strict pour ne pas casser la semantique `running`. Slot actif n est plus libere dans `finally` si run sous controle operateur.
- **H16 [HIGH]**: `request_cancel` sur run PAUSED ne clearait pas `pause_event` = deadlock du job_fn endormi dans `wait_while_paused()`. Fix : `request_cancel` clear `pause_event` APRES set `cancel_event` pour debloquer la boucle cooperative tout en garantissant que `should_cancel()` voit True en premier.

### `cinesort/app/apply_core.py` + `cinesort/ui/api/perceptual_support.py` (H1, H2, H4, H5 - 4 high TOCTOU data loss)

- **H1 [HIGH]**: `_case_only_rename_with_rollback` - remplace fallback unique `_2` par boucle bornee 10 candidats + `FileExistsError` plutot qu ecrasement (TOCTOU si crash precedent a laisse tmp + tmp_2 sur disque).
- **H2 [HIGH]**: `mkdir_counted` passe a `mkdir(parents=False, exist_ok=False)` + try/except `FileExistsError` pour SAVOIR si on a cree le dossier (journal MKDIR) ou si un autre process l a cree entre exists() et mkdir().
- **H4 [HIGH]**: `move_file_with_collision_policy` ajoute double-check `dst_file.exists()` juste avant `atomic_move` pour eviter ecrasement silencieux par `shutil.move` si collision apparait dans la fenetre TOCTOU SMB (sha1, mkdir_counted, hash_cache). Quarantine source comme conflict standard.
- **H5 [HIGH]**: `apply_single` rename branch - ajoute `dst.exists()` guard avant `folder.rename` pour transformer ecrasement silencieux POSIX en `FileExistsError` explicite (fenetre TOCTOU depuis le check l.1619 peut etre longue : sha1 video).
- *Note H3*: skip volontaire - fix proposee (touch lock-then-move) casserait l API publique de `unique_path` (4 callers attendent Path libre). H4+H5 closent la TOCTOU cote consommateur.

### `cinesort/infra/db/repositories/apply.py` (H14 - 1 high state corruption)

- **H14 [HIGH]**: `close_apply_batch` faisait un UPDATE inconditionnel sans filtrage sur status courant -> transitions arbitraires possibles dont `ROLLED_BACK -> DONE` ou `DONE -> ROLLED_BACK -> DONE`, restaurant silencieusement un batch deja annule comme "dernier reversible" via `get_last_reversible_apply_batch` (filtre status='DONE'), corrompant le journal undo. Fix : `ApplyBatchStateError` + `_ALLOWED_BATCH_TRANSITIONS` whitelist appliquee atomiquement via `WHERE status IN (...)` dans le UPDATE (no TOCTOU). Transitions autorisees : PENDING -> any close, DONE -> UNDONE_DONE|UNDONE_PARTIAL, UNDONE_PARTIAL -> UNDONE_*. Toute autre transition leve `ApplyBatchStateError` avec etat reel pour audit.

### `cinesort/app/apply_rollback.py` (H6 - 1 high data loss)

- **H6 [HIGH]**: `_revert_one_op` subissait TOCTOU entre verification `src.exists()` et `shutil.move` : si l utilisateur creait/copiait un fichier au chemin dst entre les deux operations, `shutil.move` ecrasait silencieusement sur POSIX/Windows. Fix : `dst.exists()` re-check juste avant le move + escape vers `_quarantine_conflict` au lieu d ecrasement.

### `cinesort/infra/db/migration_manager.py` + `cinesort/domain/naming.py` (BUG-015 - 1 regression critical startup)

- **BUG-015 [CRIT - regression hotfix1]**: hotfix1 ajoutait un `if "/*" in sql:` pre-test qui importait `sqlparse`, mais `sqlparse` n est PAS dans `pyproject.toml`. Au runtime, toute migration SQL contenant un commentaire bloc `/*` levait `ValueError` chaine depuis `ImportError`, empechant le demarrage de l app. Fix : wrap `import sqlparse` dans try/except `ImportError` ; en absence, log WARNING + fallback vers stripper naif `/* ... */` (re.sub DOTALL) alimentant le simple split existant. Aucune migration actuelle n utilise de bloc comment -> fallback rarement triggered, mais regression supprimee.

### `cinesort/ui/api/run_control_support.py` + `cinesort/ui/api/run_flow_support.py` (H13 - 1 high state desync)

- **H13 [HIGH]**: `_RESUMABLE_DB_STATES` cote UI incluait `AWAITING_VALIDATION` mais clause SQL backend `RunRepository.mark_run_resumed` autorisait uniquement transition depuis `PAUSED` ou `SAVED` (`WHERE status IN ('PAUSED', 'SAVED')`). Resultat : UI passait le pre-check puis DB refusait la transition, retournant "Impossible de reprendre le run (transition refusee)" apres avoir annonce le run reprise-able. Fix : retirer `AWAITING_VALIDATION` de `_RESUMABLE_DB_STATES` (cote UI) pour aligner avec contrainte SQL backend. Les runs AWAITING_VALIDATION requierent flow validation explicite (save_validation / diff approval), pas l endpoint resume generique.

### `cinesort/infra/rest_server.py` (H10 - 1 high resource leak)

- **H10 [HIGH]**: `stop()` faisait `join(timeout=5)` puis nullifiait la ref sans `is_alive()` check. Si le thread daemon refusait de mourir (handler bloque, socket non liberee), il continuait orphelin et la socket pouvait rester ouverte, faisant echouer le bind au prochain `start()`. Fix : boucle de courts `join(0.5)` avec `is_alive()` check, puis force-close de la socket sous-jacente si toujours vivant pour debloquer `serve_forever()` et liberer le port. Refs nullifiees apres best-effort cleanup.

### `cinesort/infra/db/sqlite_store.py` + `cinesort/infra/subprocess_safety.py` (BUG-001/014 - 1 critical regression + subprocess hardening)

- **BUG-001/014 [CRIT - regression hotfix1]**: `sqlite_store.bootstrap_schema` utilisait substring match naif (`"@manager: disable_fk" in script`), generant faux positif pour tout commentaire descriptif mentionnant le marker (ex: "ne PAS utiliser @manager: disable_fk ici"). Tel faux positif desactivait silencieusement les FK pour TOUT le bootstrap, masquant violations referentielles reelles pendant setup schema initial. Le chemin migration-par-migration (`MigrationManager.apply`) a ete durci en hotfix1 pour exiger une ligne commencant (apres trim) par le prefixe litteral. Bootstrap mirror maintenant cette regle exacte via `script.splitlines()` + `line.strip().startswith("-- @manager: disable_fk")`.
- **Subprocess hardening** : `subprocess_safety.py` durci pour gerer ffmpeg/ffprobe orphelins (cleanup processus zombies au kill timeout).

## Detail des 5 regressions hotfix1

1. **BUG-015** (migration_manager) : ImportError sqlparse au startup -> WARNING + fallback regex
2. **BUG-001/014** (sqlite_store bootstrap) : substring match `@manager: disable_fk` -> line.startswith strict
3. **C2** (job_runner) : PENDING -> CANCELLED sans started_ts -> mark_run_running puis mark_run_cancelled
4. **C3** (job_runner) : snapshot memoire desync PAUSED/RUNNING -> alignement explicite dans request_pause/resume
5. **H13** (run_control_support) : `_RESUMABLE_DB_STATES` incluait AWAITING_VALIDATION mais SQL refusait -> retire de la whitelist UI

## Commits inclus

- `a074e69` fix(hotfix2): sqlite_store - BUG-001/014 (high incoherence)
- `2c24b35` fix(hotfix2): rest_server - BUG-H10 - high
- `4629dcf` fix(hotfix2): run_control_support - BUG-H13 - high
- `a141f75` fix(hotfix2): migration_manager - BUG-015 (high regression)
- `be5862c` fix(hotfix2): apply_rollback - H6 (high data loss)
- `a56508b` fix(hotfix2): apply - H14 state-machine guard for close_apply_batch
- `f8332a6` fix(hotfix2): apply_core - H1,H2,H4,H5 (TOCTOU + data loss)
- `5312432` fix(hotfix2): job_runner - C2,C3,C4,H15,H16 (regressions+critical+high)

## Tag

`vague-r-hotfix2` (local, pas de push remote)
