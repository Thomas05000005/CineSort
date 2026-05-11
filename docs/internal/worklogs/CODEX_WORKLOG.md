# CODEX Worklog - Release Audit

## Session Setup (2026-02-21)
- Branche creee: `release_audit_20260221`
- Tag cree: `pre_release_audit`
- Backup initial cree: `_BACKUP_patch_before.txt` via `git diff > _BACKUP_patch_before.txt`
- Audit structure confirme: `app.py -> backend.py -> cinesort/ui/api/cinesort_api.py -> core.py`
- Endpoints API verifies et coherents:
  - `start_plan`, `get_status`, `get_plan`
  - `load_validation`, `save_validation`, `check_duplicates`
  - `apply`, `open_path`
  - `get_settings`, `save_settings`, `test_tmdb_key`

## Commit Lot 1 - Merge/Conflict hardening (core + tests)
### Fichiers
- `core.py`
- `tests/test_merge_duplicates.py`

### Changements
- Ajout classification sidecar/metadata explicite.
- Strategie collision:
  - identique -> soft-delete vers `_review/_duplicates_identical`
  - sidecar different -> keep-both vers `_review/_conflicts_sidecars` avec `incoming_<hash8>`
  - non-sidecar different -> conflit dur vers `_review/_conflicts`
- Chemins `_review` rendus uniques et contextuels:
  - `<dst_rel>/__from__/<src_rel>/...`
- Conflits et duplicates avec suffixes anti-collision.
- Tests ajoutes/etendus:
  - `test_sidecar_conflict_kept_both_does_not_block_merge`
  - `test_conflict_paths_are_unique`
  - verification soft-delete duplicates identiques.

### Tests lances
- `python -m unittest -v tests.test_merge_duplicates`
- Resultat: OK (8 tests).

## Commit Lot 2 - API summary & action required
### Fichiers
- `cinesort/ui/api/cinesort_api.py`
- `tests/test_backend_flow.py`

### Changements
- Enrichissement des logs finaux APPLY avec compteurs sidecar.
- Ajout d'une section `ACTION REQUISE` dans `summary.txt` quand necessaire:
  - `_review/_conflicts`
  - `_review/_conflicts_sidecars`
  - `_review/_duplicates_identical`
  - `_review/_leftovers`
- Test backend flow etendu pour verifier la presence des compteurs summary.

### Tests lances
- `python -m unittest -v tests.test_backend_flow tests.test_api_bridge_lot3`
- Resultat: OK (12 tests).

## Commit Lot 3 - Release hygiene et fenetre
### Fichiers
- `tests/test_release_hygiene.py`
- `app.py`

### Changements
- Exclusion explicite des artefacts backup (`_BACKUP_patch_before.txt`, `_BACKUP_patch_after.txt`) du test hygiene.
- Correction du titre fenetre pour eviter un texte corrompu et garantir un affichage stable:
  - `CineSort - Tri & normalisation de bibliotheque films`

### Tests lances
- `python -m unittest -v tests.test_release_hygiene`
- Resultat: OK (1 test).

## Final Validation - Release Readiness
### Commandes executees
- `python -m py_compile <tous les .py>`
- `python -m unittest discover -s tests -p "test_*.py" -v`
- `python -m unittest -v tests.test_backend_flow tests.test_core_heuristics tests.test_job_runner tests.test_api_bridge_lot3 tests.test_v7_foundations tests.test_merge_duplicates`
- `pyinstaller --clean --noconfirm CineSortApp.spec`

### Resultats
- `py_compile`: OK
- `unittest discover`: OK (52 tests)
- `suite ciblee`: OK (51 tests)
- `pyinstaller`: OK (EXE genere dans `dist/CineSort.exe`)
  - Note: un premier essai a echoue sans Pillow; correction environnement appliquee via `python -m pip install pillow`, puis build relance avec succes.

### Checklist release
- [x] Flux execution verifie: `app.py -> backend.py -> CineSortApi -> core.py`
- [x] Endpoints API v6 verifies et coherents
- [x] Merge dossier existant non bloquant
- [x] Collisions sans overwrite silencieux
- [x] Sidecar conflicts en keep-both
- [x] Duplicates identiques en soft-delete
- [x] Paths `_review` contextuels et uniques
- [x] Summary + action requise explicites
- [x] Hygiene placeholders/strings perso verifiee
- [x] Packaging spec valide (web + migrations + icon + nom CineSort)

### Backups
- `_BACKUP_patch_before.txt` genere au debut de mission.
- `_BACKUP_patch_after.txt` regenere en fin de mission avec:
  - `git diff pre_release_audit..HEAD > _BACKUP_patch_after.txt`

## Session 7.1.3-dev (2026-02-22)
- Branche creee: `v7_1_score`
- Tag cree: `pre_v7_1_score`
- Backup initial cree: `_BACKUP_patch_before_v7_1_3.txt`

### Lot A - DB + moteur CinemaLux
- Ajout migration `cinesort/infra/db/migrations/003_quality_score_tables.sql`.
- Ajout module `cinesort/domain/quality_score.py` (score 0-100, tiers, reasons FR, metrics, 4K Light).
- Extension `SQLiteStore`:
  - schema fallback v3,
  - tables `quality_profiles`/`quality_reports`,
  - CRUD profil actif + upsert/get report.

### Lot B - API + UI Qualite
- `cinesort/ui/api/cinesort_api.py`:
  - endpoints: `get_quality_profile`, `save_quality_profile`, `reset_quality_profile`, `export_quality_profile`, `import_quality_profile`, `get_quality_report`.
  - scoring branché sur probe 7.1.2 + persistance DB des rapports.
- UI web:
  - nouvel onglet `Qualite` (`web/index.html`),
  - logique formulaire/profil/test film (`web/app.js`),
  - styles utilitaires (`web/styles.css`).

### Lot C - tests + version
- Ajout `tests/test_quality_score.py`.
- Mise a jour schema attendu v3 dans `tests/test_v7_foundations.py` et `tests/test_api_bridge_lot3.py`.
- Mise a jour `check_project.bat` (compile + unittest include quality).
- Mise a jour `CHANGELOG.md` et `VERSION` -> `7.1.3-dev`.

### Tests executes
- `python -m py_compile cinesort\domain\quality_score.py cinesort\infra\db\sqlite_store.py cinesort\ui\api\cinesort_api.py tests\test_quality_score.py` -> OK
- `python -m unittest -v tests.test_quality_score` -> OK (5 tests)
- `python -m unittest -v tests.test_v7_foundations tests.test_api_bridge_lot3` -> OK (16 tests)

## Session 7.1.4-dev (2026-02-22)
- Branche creee: `v7_1_4_dashboard`
- Tag cree: `pre_v7_1_4_dashboard`
- Backup initial cree: `_BACKUP_patch_before_v7_1_4.txt`

### Lot A - DB/API dashboard
- Ajout migration `004_anomalies_table.sql`.
- Extension `SQLiteStore`:
  - support table `anomalies` dans fallback schema v4,
  - helper `list_anomalies_for_run`,
  - helper agregation `get_anomaly_counts_for_runs`.
- Ajout endpoint `CineSortApi.get_dashboard(run_id|latest)`:
  - KPIs, distributions, outliers, anomalies, historique runs.
  - fallback robuste si run absent ou non score.

### Lot B - UI dashboard
- `web/index.html`: nouvel onglet `Dashboard` + sections:
  - cartes KPI,
  - distributions,
  - top anomalies,
  - outliers,
  - historique runs.
- `web/app.js`:
  - chargement via un seul appel `get_dashboard`,
  - rendu complet + bouton rafraichir,
  - boutons `Ouvrir` relies a `open_path`.
- `web/styles.css`: styles lisibles pour cartes/barres/tableaux dashboard.

### Lot C - tests + versionning
- Ajout `tests/test_dashboard.py`:
  - cohérence payload dashboard,
  - bins/sections/outliers,
  - fallback `latest` et run non score.
- Mise a jour `check_project.bat` (compile + unittest incluent `test_dashboard`).
- Mise a jour `CHANGELOG.md` + `VERSION` -> `7.1.4-dev`.
- Hygiene repo/package:
  - `.gitignore` ajuste pour versionner `cinesort/infra/db/migrations/*.sql`,
  - `CineSortApp.spec` ajuste pour embarquer explicitement les migrations SQL.

### Validation executee (7.1.4-dev)
- `python -m py_compile cinesort\infra\db\sqlite_store.py cinesort\ui\api\cinesort_api.py tests\test_dashboard.py tests\test_v7_foundations.py tests\test_api_bridge_lot3.py` -> OK
- `python -m unittest -v tests.test_dashboard` -> OK (2 tests)
- `python -m unittest discover -s tests -p "test_*.py" -v` -> OK (64 tests)
- `.\check_project.bat` -> OK
- `pyinstaller --clean --noconfirm CineSortApp.spec` -> OK

## Session 7.1.5-dev (2026-02-22)
- Branche creee: `v7_1_5_ui`
- Tag cree: `pre_v7_1_5_ui`
- Backup initial cree: `_BACKUP_patch_before_v7_1_5_ui.txt`

### Lot A - UI premium navigation + contexte
- Navigation regroupee en 2 blocs:
  - `WORKFLOW`: Parametres, Analyse, Validation, Doublons, Application, Journaux
  - `INSIGHTS`: Qualite, Dashboard
- Renforcement accessibilite:
  - roles ARIA `tablist/tab/tabpanel`,
  - focus visible,
  - navigation clavier onglets (fleches, Enter/Espace).
- Ajout bandeau `Contexte courant`:
  - run actif (copie + ouverture dossier run),
  - film selectionne (titre/annee),
  - mode avance (affichage/copie `row_id`).
- Ajout modal `Selectionner…` pour choisir run + film sans saisie manuelle.

### Lot B - logique selection auto run/film
- `start_plan` alimente `lastRunId` + stockage local.
- Clic sur une ligne Validation definit le film actif (`selectedRunId/selectedRowId`).
- Qualite:
  - bouton principal "Tester sur le film selectionne",
  - fallback: dernier run + ouverture du selecteur.
- Dashboard:
  - charge `latest` par defaut,
  - champ `run_id` visible uniquement en mode avance.

### Validation executee (7.1.5-dev)
- `python -m unittest discover -s tests -p "test_*.py" -v` -> OK (64 tests)

## Session docs patch (2026-02-22)
- Ajout dans `V7_1_NOTES_FR.md` d'une section "Style Guide CineSort (UI premium)" (10 regles).
- Ajout dans `V7_1_NOTES_FR.md` d'une section "Checklist smoke UI (7.1.5)" (10 points de verification).
- Aucun changement code/app/API: patch documentation uniquement.

## Session 7.2.0-A (cadrage) - 2026-03-02
### Lot L - Undo design-first
- Ajout du document `UNDO_7_2_0_A_DESIGN_FR.md`:
  - objectif/contraintes undo,
  - schema DB propose (`apply_batches`, `apply_operations`),
  - endpoints API non-breaking proposes (`undo_last_apply_preview`, `undo_last_apply`),
  - strategie rollback (LIFO, no-overwrite, conflits vers `_review/_undo_conflicts`),
  - plan de tests et ordre d'implementation.
- Mise a jour `README_FR.txt` avec l'entree de lot L pour partage.

## Session 7.2.0-A (implementation) - 2026-03-02
### Lot M - Undo v1 (DB + core + API + tests)
- Ajout migration `cinesort/infra/db/migrations/005_apply_undo_journal.sql`.
- Extension `cinesort/infra/db/sqlite_store.py`:
  - journal apply (`insert_apply_batch`, `append_apply_operation`, `close_apply_batch`),
  - lecture undo (`get_last_reversible_apply_batch`, `list_apply_operations`),
  - statuts undo (`mark_apply_operation_undo_status`, `mark_apply_batch_undo_status`),
  - schema fallback passe en user_version 5.
- Instrumentation `core.py`:
  - hook optionnel `record_op` dans `apply_rows`,
  - propagation sur moves/renames/quarantine sans changer la politique metier.
- Extension `cinesort/ui/api/cinesort_api.py`:
  - `apply` journalise les ops reelles dans la DB,
  - endpoints non-breaking:
    - `undo_last_apply_preview(run_id)`,
    - `undo_last_apply(run_id, dry_run=True|False)`.
  - undo reel:
    - ordre inverse,
    - no-overwrite,
    - conflits vers `_review/_undo_conflicts`,
    - section `=== RESUME UNDO ===` ecrite dans `summary.txt`.
- Tests:
  - nouveau `tests/test_undo_apply.py`,
  - mise a jour schema version dans `tests/test_v7_foundations.py` et `tests/test_api_bridge_lot3.py`.
- Validation:
  - `python -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py" -v` -> OK (119 tests),
  - `.\check_project.bat` -> OK.

## Session 7.2.0-A (UI) - 2026-03-02
### Lot N - Undo UI Application
- Ajout UI dans `web/index.html`:
  - section Undo sous le resultat apply,
  - actions `Prévisualiser Undo` / `Lancer Undo`,
  - toggle dry-run et zone resultat.
- Ajout logique front dans `web/app.js`:
  - `refreshUndoPreview(...)`,
  - `runUndoFromUI(...)`,
  - formatters preview/resultat Undo,
  - gardes anti concurrence avec apply,
  - confirmation explicite avant Undo reel.
- Flux:
  - preview Undo charge automatiquement a l'ouverture de la vue Application,
  - preview rafraichi automatiquement apres apply reel.
- Validation:
  - `python -m unittest -v tests.test_ui_logic_contracts` -> OK,
  - `python -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py" -v` -> OK (119 tests).

## Session 7.2.0-B (implementation) - 2026-03-02
### Lot O - Scan incremental (mode changements)
- Ajout migration SQL `cinesort/infra/db/migrations/006_incremental_scan_cache.sql`:
  - table `incremental_file_hashes` (path/size/mtime_ns/hash quick),
  - table `incremental_scan_cache` (cache dossier + signatures + rows/stats).
- Extension `cinesort/infra/db/sqlite_store.py`:
  - lecture/ecriture hash quick incremental,
  - lecture/ecriture cache dossier incremental,
  - purge cache dossiers disparus,
  - schema fallback passe a user_version `6`.
- Extension `core.py`:
  - `Config.incremental_scan_enabled`,
  - stats cache incremental (`hits/misses/rows_reused`),
  - signature config incremental,
  - serialisation/deserialisation `PlanRow` pour cache,
  - reutilisation rows+stats par dossier si signature inchangee,
  - invalidation automatique sur changement + purge fin de scan.
- Extension API `cinesort/ui/api/cinesort_api.py`:
  - nouveau setting `incremental_scan_enabled`,
  - propagation vers `core.Config`,
  - branchement `scan_index=store` quand mode incremental actif,
  - resume analyse enrichi (cache incremental).
- Tests:
  - nouveau `tests/test_incremental_scan.py`:
    - exactitude scan complet vs incremental,
    - invalidation sur dossier modifie,
    - perf relative (2e passe comparable/meilleure),
  - MAJ `tests/test_v7_foundations.py` et `tests/test_api_bridge_lot3.py` (schema version `6`),
  - MAJ `check_project.bat` (compile inclut `test_incremental_scan.py`).
- Validation:
  - `python -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py" -v` -> OK (122 tests),
  - `.\check_project.bat` -> OK.

## Session 7.2.0-C (implementation) - 2026-03-02
### Lot P - File "A relire" intelligente
- Extension front `web/app.js`:
  - ajout `computeReviewRisk(row, decision)` (score de risque 0..100),
  - preset `review_risk` base sur un seuil de risque explicite,
  - tri prioritaire des lignes les plus risquées en tete,
  - badge de risque + tooltip analyse enrichi quand preset actif,
  - message de synthese utilisateur sur la file a relire.
- Contrat UI:
  - MAJ `tests/test_ui_logic_contracts.py` pour verifier presence scoring + sorting du preset risque.
- Validation:
  - `python -m unittest tests.test_ui_logic_contracts -v` -> OK,
  - `.\check_project.bat` -> OK (123 tests).

## Session 7.2.0-D (implementation) - 2026-03-02
### Lot Q - Presets qualite prets a l'emploi
- Extension domaine `cinesort/domain/quality_score.py`:
  - catalogue presets `remux_strict`, `equilibre`, `light`,
  - helpers `list_quality_presets(...)` et `quality_profile_from_preset(...)`.
- Extension API non-breaking `cinesort/ui/api/cinesort_api.py`:
  - endpoint `get_quality_presets()`,
  - endpoint `apply_quality_preset(preset_id)`.
- Extension UI Hub Qualite:
  - nouveaux boutons presets dans `web/index.html`,
  - chargement presets + application en un clic dans `web/app.js`,
  - preset actif surligne via `web/styles.css`.
- Tests:
  - MAJ `tests/test_quality_score.py` (catalogue presets, endpoint API, persistence preset, strict vs light).

## Session audit/correctifs - 2026-03-06
### Lot R - Clarification batch qualite "films valides"
- Ajout du memo `AUDIT_CORRECTIFS_PROJET_FR.txt`:
  - rappel du projet,
  - constats d'audit prioritaires,
  - ordre de correction retenu pour les prochains lots.
- Correction faible risque dans `web/index.html` et `web/app.js`:
  - `Analyser toute la selection` devient `Analyser tous les films valides`,
  - helper renomme en `validatedRowIdsForQualityBatch()`,
  - messages batch alignes sur le comportement reel.
- Tests:
  - MAJ `tests/test_ui_logic_contracts.py` pour verrouiller le libelle et la semantique front.
- Validation locale:
  - `python -m unittest -v tests.test_ui_logic_contracts` -> OK (9 tests),
  - `check_project.bat` actuellement bloque localement par des `PermissionError [WinError 5]` sur `tempfile.TemporaryDirectory` dans de nombreux tests non lies a ce lot,
  - point complementaire a confirmer plus tard sur `tests.test_tmdb_client` / `TmdbClient.flush()`.

### Lot S - Reset decisions sur changement de run qualite
- Correction front faible risque dans `web/app.js`:
  - `ensureQualityRowsForRun(...)` vide `state.decisions` juste apres `setRows(...)`,
  - les decisions ne sont reappliquees que si `load_validation(...)` du nouveau run reussit.
- But:
  - eviter qu'un ancien run laisse des validations en memoire si le chargement du nouveau run echoue.
- Tests:
  - MAJ `tests/test_ui_logic_contracts.py` pour verrouiller l'ordre `reset -> load_validation`.

### Lot T - ROOT sans fallback implicite sur payload partiel
- Durcissement backend dans `cinesort/ui/api/cinesort_api.py`:
  - ajout helper `_read_saved_root_candidates(...)`,
  - `save_settings(...)` reutilise le ROOT reellement sauvegarde si `root` est absent,
  - `start_plan(...)` reutilise le ROOT sauvegarde si `root` est absent,
  - si aucun ROOT sauvegarde n'existe: erreur explicite au lieu d'un fallback vers `D:\Films`,
  - si `state_dir` est fourni explicitement, la resolution reste bornee a ce contexte.
- Tests:
  - MAJ `tests/test_api_bridge_lot3.py`:
    - reuse saved root,
    - reject when no saved root exists,
    - preserve explicit empty-root rejection.
- Validation:
  - `python -m unittest -v tests.test_api_bridge_lot3` -> OK (28 tests),
  - `python -m unittest -v tests.test_backend_flow` -> OK (2 tests).

### Lot U - Recursivite scan plus sure sur dossiers parents avec bonus
- Correction prudente dans `core.py`:
  - ajout d'une detection des videos d'extras generiques au parent (`bonus`, `extras`, `featurettes`, etc.),
  - `_iter_scan_targets(...)` continue la descente si le parent ne contient que ces videos et possede des sous-dossiers.
- But:
  - eviter qu'un parent "mixte" coupe la recursivite et masque des sous-dossiers films legitimes.
- Tests:
  - MAJ `tests/test_core_heuristics.py` avec un cas `Bonus.mkv` au parent + sous-dossiers films,
  - test existant sur collections imbriquees conserve.
- Validation:
  - `python -m unittest -v tests.test_core_heuristics` -> OK (22 tests).

### Lot V - Export CSV compatible Excel Windows
- Correction backend dans `cinesort/ui/api/cinesort_api.py`:
  - `export_run_report(..., "csv")` ecrit maintenant en `utf-8-sig`.
- But:
  - eviter les accents FR mal lus dans Excel Windows.
- Tests:
  - MAJ `tests/test_run_report_export.py` pour verifier le BOM CSV.
- Validation:
  - `python -m unittest -v tests.test_run_report_export` -> OK (3 tests).

### Lot W - Etat preset qualite plus juste apres edition
- Correction UI dans `web/app.js`:
  - ajout `qualityProfileFingerprint(...)`,
  - `renderQualityPresetButtons()` compare maintenant le profil courant au preset complet,
  - etat `active` seulement en cas de match exact,
  - nouvel etat visuel `derived` si le preset a ete modifie manuellement.
- Extension API non-breaking:
  - `cinesort/ui/api/cinesort_api.py:get_quality_presets()` renvoie aussi `profile_json`.
- Style:
  - ajout d'un rendu CSS `qualityPresetBtn.derived` dans `web/styles.css`.
- Tests:
  - MAJ `tests/test_ui_logic_contracts.py`,
  - MAJ `tests/test_quality_score.py` sur `get_quality_presets`.
- Validation:
  - `python -m unittest -v tests.test_ui_logic_contracts` -> OK (11 tests),
  - `python -m unittest -v tests.test_quality_score.QualityScoreTests.test_api_get_quality_presets_returns_expected_ids` -> OK.

### Lot X - 7A / 7B1 garde-fous + extraction helpers settings/root/state_dir
- 7A:
  - MAJ `tests/test_api_bridge_lot3.py` avec deux garde-fous supplementaires:
    - `save_settings(...)` ne doit pas reutiliser un ROOT d'un autre `state_dir` quand le `state_dir` cible est explicite,
    - `start_plan(...)` idem.
- 7B1:
  - extraction dans `cinesort/ui/api/cinesort_api.py` de:
    - `_resolve_payload_state_dir(...)`,
    - `_resolve_root_from_payload(...)`.
  - `save_settings(...)` et `start_plan(...)` passent maintenant par ces helpers prives.
- But:
  - reduire la duplication,
  - garder un seul point de verite pour la resolution `ROOT/state_dir`,
  - preparer les lots suivants de dette structurelle sans changer l'API publique.
- Validation:
  - `python -m unittest -v tests.test_api_bridge_lot3` -> OK (30 tests),
  - `python -m unittest -v tests.test_backend_flow` -> OK (2 tests).

### Lot Y - 7B2 extraction helpers profil qualite + export run
- Extraction interne dans `cinesort/ui/api/cinesort_api.py`:
  - `_quality_store(...)`,
  - `_active_quality_profile_payload(...)`,
  - `_save_active_quality_profile(...)`,
  - `_write_run_report_file(...)`.
- Endpoints publics refactorises sans changer leur contrat:
  - `get_quality_profile()`,
  - `apply_quality_preset()`,
  - `save_quality_profile()`,
  - `reset_quality_profile()`,
  - `export_quality_profile()`,
  - `export_run_report()`.
- But:
  - retirer la duplication locale,
  - preparer les prochains sous-lots sur `cinesort_api.py` sans toucher a l'API v6.
- Validation:
  - `python -m unittest -v tests.test_quality_score.QualityScoreTests.test_api_get_quality_presets_returns_expected_ids tests.test_quality_score.QualityScoreTests.test_apply_quality_preset_persists_active_profile tests.test_quality_score.QualityScoreTests.test_profile_reset_restore_defaults tests.test_quality_score.QualityScoreTests.test_profile_import_invalid_returns_fr_error` -> OK (4 tests),
  - `python -m unittest -v tests.test_run_report_export tests.test_api_bridge_lot3` -> OK (33 tests).

### Lot Z - 7C1 decoupage front: services UI transverses
- Nouveau fichier `web/ui_shell.js`:
  - `$`, `qsa`,
  - messages de statut,
  - feedback boutons,
  - `apiCall(...)`,
  - `openPathWithFeedback(...)`,
  - modales / `uiConfirm(...)` / `uiInfo(...)`.
- `web/app.js`:
  - suppression des doublons correspondants,
  - conservation de l'etat global et du workflow metier.
- `web/index.html`:
  - chargement explicite `ui_shell.js` avant `app.js`.
- Tests:
  - refonte de `tests/test_ui_logic_contracts.py` pour verifier le front comme ensemble `ui_shell.js + app.js`.
- Validation:
  - `python -m unittest -v tests.test_ui_logic_contracts` -> OK (12 tests).

### Lot AA - 7D1 extraction helpers purs de scan
- Nouveau fichier `core_scan_helpers.py`:
  - `iter_scan_targets(...)`,
  - `iter_videos(...)`,
  - `detect_single_with_extras(...)`,
  - `collect_non_video_extensions(...)`,
  - constantes/helpers de pruning prudent sur extras/bonus.
- `core.py`:
  - suppression des doublons locaux correspondants,
  - import explicite des helpers de scan depuis `core_scan_helpers.py`,
  - flux principal conserve sans toucher a `apply_rows`.
- But:
  - reduire la taille et le couplage local de `core.py`,
  - isoler les helpers purs de scan a faible risque avant d'autres extractions.
- Validation:
  - `python -m unittest -v tests.test_core_heuristics` -> OK (22 tests),
  - `python -m unittest -v tests.test_backend_flow` -> OK (2 tests).

### Lot AB - 7C2 decoupage front: modules Validation + Qualite
- Nouveaux fichiers:
  - `web/ui_validation.js`
  - `web/ui_quality.js`
- `web/ui_validation.js`:
  - extraction des helpers de filtres validation,
  - score de risque de relecture,
  - rendu table,
  - modal candidats/propositions.
- `web/ui_quality.js`:
  - extraction du profil qualite,
  - presets qualite,
  - outils probe,
  - test qualite unitaire,
  - batch qualite.
- `web/index.html`:
  - chargement explicite `ui_shell.js`, `ui_validation.js`, `ui_quality.js`, puis `app.js`.
- `web/app.js`:
  - conserve l'etat global, le bootstrap, les hooks et l'orchestration.
- Tests:
  - MAJ `tests/test_ui_logic_contracts.py` pour verifier la chaine front complete et la presence des modules extraits.
- Validation:
  - `python -m unittest -v tests.test_ui_logic_contracts` -> OK (14 tests),
  - `python -m unittest -v tests.test_backend_flow tests.test_core_heuristics` -> OK (24 tests).

### Lot AC - 7D2 extraction heuristiques pures titre/annee
- Nouveau fichier `core_title_helpers.py`:
  - `extract_year(...)`,
  - `extract_all_years(...)`,
  - `infer_name_year(...)`,
  - `clean_title_guess(...)`,
  - `title_match_score(...)`,
  - `tokens(...)`,
  - `_expand_tmdb_queries(...)`,
  - `_extract_trailing_sequel_num(...)`,
  - `_title_similarity(...)`,
  - `_tmdb_prefix_equivalent(...)`,
  - `_norm_for_tokens(...)`.
- `core.py`:
  - suppression des definitions locales correspondantes,
  - import explicite depuis `core_title_helpers.py`,
  - restauration/conservation des helpers NFO, TV-like et cancellation non vises par l'extraction.
- Incremental:
  - reconstitution du socle interne utilise par `plan_library(...)`:
    - signature config,
    - snapshot/delta stats,
    - serialisation `PlanRow`,
    - signature de dossier,
    - quick-hash incrementaux.
- Tests:
  - ajout d'un test sur `_expand_tmdb_queries(...)`.
- Validation:
  - `python -m unittest -v tests.test_core_heuristics tests.test_backend_flow tests.test_incremental_scan` -> OK (28 tests).

## Session 7E (cadrage apply_rows) - 2026-03-07
### Lot AD - Design doc strict avant refactor
- Analyse de `core.apply_rows(...)` et des helpers sensibles associes:
  - `_apply_single(...)`,
  - `_apply_collection_item(...)`,
  - `_quarantine_row(...)`,
  - `_migrate_legacy_collection_root(...)`,
  - `_move_empty_top_level_dirs(...)`.
- Ajout du document `APPLY_ROWS_7E_DESIGN_FR.md`:
  - invariants metier et medias a conserver,
  - cartographie des responsabilites actuelles de `apply_rows(...)`,
  - proposition de decomposition progressive,
  - ordre d'extraction faible risque,
  - matrice de non-regression obligatoire avant refactor code.
- Decision explicite:
  - aucun changement de comportement dans ce lot,
  - pas de reecriture brutale de `apply_rows(...)`,
  - le prochain sous-lot code recommande est l'extraction du contexte apply.

### Validation
- Pas de tests executes:
  - lot de cadrage/documentation uniquement,
  - aucun changement de code de production.

## Session 7E1 (implementation apply_rows context) - 2026-03-07
### Lot AE - Extraction du contexte apply
- `core.py`:
  - ajout de `ApplyExecutionContext`,
  - ajout du helper `_build_apply_context(...)`,
  - `apply_rows(...)` delegue maintenant son initialisation a ce helper.
- Perimetre volontairement strict:
  - aucune modification du dispatch `single/collection/quarantine`,
  - aucune modification des `skip_reasons`,
  - aucune modification des hooks `record_op(...)`.
- Test ajoute:
  - `tests.test_v7_1_features.V71FeaturesTests.test_build_apply_context_prepares_roots_and_decision_keys`
- Validation:
  - `python -m unittest -v tests.test_v7_1_features` -> OK (6 tests),
  - `python -m unittest -v tests.test_merge_duplicates` -> OK (9 tests),
  - `python -m unittest -v tests.test_undo_apply tests.test_backend_flow` -> OK (4 tests).

## Session UI redesign (refonte architecture visuelle) - 2026-03-07
### Lot AF - Refonte UI/UX conservative
- Backup UI cree avant modification:
  - `.ui_backups\\index.before_ui_redesign.html`
  - `.ui_backups\\app.before_ui_redesign.js`
  - `.ui_backups\\styles.before_ui_redesign.css`
- `web/index.html`:
  - conservation des ids DOM et des vues `.view`,
  - reorganisation des pages en layouts plus explicites,
  - ajout de rails de guidance pour `Parametres`, `Qualite`, `Validation`, `Application`,
  - alignement du hint run initial avec la logique actuelle.
- `web/styles.css`:
  - nouveau shell visuel plus premium,
  - topbar sticky,
  - cartes hero/rails,
  - sidebar compacte sur petite largeur au lieu de disparaitre,
  - hierarchie et contraste renforces sans changement metier.
- `web/app.js`:
  - ajout du hook `document.body.dataset.view` dans `showView(...)`.
- Validation:
  - `python -m unittest -v tests.test_ui_logic_contracts` -> OK (28 tests),
  - `check_project.bat` -> OK,
  - `python -W error::ResourceWarning -m unittest discover -s tests -p "test_*.py" -v` -> OK (158 tests).
