# CineSort 7.2.0-A - Design Technique Undo du dernier apply

## 1) Objectif
Permettre un retour arriere controle du dernier apply **reel** (pas dry-run), avec:
- previsualisation avant execution,
- rollback securise, tracable et idempotent,
- aucun changement destructif medias.

## 2) Contraintes non-negociables
- Compat API v6 strictement conservee (endpoints existants inchanges).
- Aucun comportement destructif medias.
- Politique actuelle conservee: quarantaine / soft-delete / no-overwrite.
- Echec partiel d'undo doit etre observable et non silencieux.
- Undo limite au **dernier apply valide** d'un run (v1).

## 3) Perimetre v1 (7.2.0-A)
Inclus:
- journalisation atomique des operations apply reelles,
- endpoint preview undo,
- endpoint undo dry-run + reel,
- logs + resume d'undo.

Exclus (v1):
- undo multi-batch arbitraire,
- undo inter-runs en chaine,
- rollback binaire externe (Plex/Jellyfin),
- restauration d'operations irreversibles hors quarantaine.

## 4) Strategie metier
### 4.1 Operations reversibles v1
Reversibles:
- move/rename dossier,
- move/rename fichier,
- deplacements vers `_review`.

Non reversibles (v1, marquees `irreversible=true`):
- suppressions physiques si une branche les utilise encore,
- operations sans source fiable (metadata incomplete).

### 4.2 Regle d'execution
- Undo rejoue en ordre inverse (`LIFO`) du journal.
- Chaque operation est pre-validee:
  - source inverse presente,
  - destination inverse libre ou resolue via quarantaine undo.
- En cas de conflit:
  - ne pas ecraser,
  - deplacer le conflit sous `_review/_undo_conflicts`.

## 5) Schema DB propose (migration v5)
Migration proposee: `cinesort/infra/db/migrations/005_apply_undo_journal.sql`

### 5.1 Table `apply_batches`
- `batch_id TEXT PRIMARY KEY`
- `run_id TEXT NOT NULL`
- `started_ts REAL NOT NULL`
- `ended_ts REAL`
- `dry_run INTEGER NOT NULL CHECK (dry_run IN (0,1))`
- `quarantine_unapproved INTEGER NOT NULL CHECK (quarantine_unapproved IN (0,1))`
- `status TEXT NOT NULL` (`PENDING|DONE|FAILED|CANCELLED|UNDONE_PARTIAL|UNDONE_DONE`)
- `summary_json TEXT NOT NULL`
- `app_version TEXT NOT NULL`

Indexes:
- `idx_apply_batches_run_id` sur `(run_id, started_ts DESC)`

### 5.2 Table `apply_operations`
- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `batch_id TEXT NOT NULL`
- `op_index INTEGER NOT NULL`
- `op_type TEXT NOT NULL` (ex: `MOVE_FILE`, `MOVE_DIR`, `QUARANTINE_FILE`, `MKDIR`)
- `src_path TEXT NOT NULL`
- `dst_path TEXT NOT NULL`
- `reversible INTEGER NOT NULL CHECK (reversible IN (0,1))`
- `undo_status TEXT NOT NULL DEFAULT 'PENDING'` (`PENDING|DONE|SKIPPED|FAILED`)
- `error_message TEXT`
- `ts REAL NOT NULL`

Contraintes:
- `FOREIGN KEY(batch_id) REFERENCES apply_batches(batch_id)`
- `UNIQUE(batch_id, op_index)`

Indexes:
- `idx_apply_ops_batch`
- `idx_apply_ops_reversible`

## 6) Integration code (plan)
## 6.1 Core apply
Ajouter un hook optionnel `record_op(op)` dans `core.apply_rows`:
- appele uniquement pour operations reelles effectives (pas dry-run),
- payload minimal:
  - `op_type`, `src_path`, `dst_path`, `reversible`, `ts`.

## 6.2 API bridge
Dans `CineSortApi.apply(...)`:
- ouvrir un `apply_batch` avant execution,
- persister operations au fil de l'eau,
- fermer batch en `DONE/FAILED`.

Nouveaux endpoints non-breaking:
- `undo_last_apply_preview(run_id)`
- `undo_last_apply(run_id, dry_run: bool = True)`

## 6.3 Store SQLite
Extensions `SQLiteStore`:
- `insert_apply_batch(...)`
- `append_apply_operation(...)`
- `close_apply_batch(...)`
- `get_last_reversible_batch(run_id)`
- `list_apply_operations(batch_id)`
- `mark_undo_operation_status(...)`
- `mark_batch_undo_status(...)`

## 7) Algorithme undo (v1)
1. Charger dernier `apply_batch` reellment applique et non annule.
2. Construire preview:
- total ops,
- ops reversibles,
- ops irreversibles,
- conflits previsionnels.
3. Si `dry_run=true`: retourner uniquement preview + risques.
4. Si `dry_run=false`:
- iterer operations reversibles en ordre inverse,
- tenter l'operation inverse,
- journaliser statut par op,
- compter `done/skipped/failed`.
5. Statut final batch:
- `UNDONE_DONE` si 0 echec,
- `UNDONE_PARTIAL` sinon.

## 8) Observabilite
Logs FR obligatoires:
- debut undo (batch cible),
- progression (`x/y`),
- conflits vers `_review/_undo_conflicts`,
- resume final.

Fichier run:
- ajout section `=== RESUME UNDO ===` dans `summary.txt` (sans dupliquer sections existantes).

## 9) API contract propose
### `undo_last_apply_preview(run_id)`
Retour:
- `ok`
- `run_id`
- `batch_id`
- `can_undo` (bool)
- `counts` (`total`, `reversible`, `irreversible`, `conflicts_predicted`)
- `message`

### `undo_last_apply(run_id, dry_run)`
Retour:
- `ok`
- `run_id`
- `batch_id`
- `dry_run`
- `counts` (`done`, `skipped`, `failed`, `irreversible`)
- `status` (`UNDONE_DONE|UNDONE_PARTIAL|PREVIEW_ONLY`)
- `message`

## 10) Plan de tests (obligatoire)
Nouveaux tests proposes:
1. Creation journal apply sur run reel.
2. Pas de journal ecrit en dry-run.
3. Preview undo coherent (reversible/irreversible).
4. Undo succes complet (retour etat initial).
5. Undo partiel avec conflit (quarantaine `_undo_conflicts`).
6. Idempotence: second undo refuse proprement ou noop explicite.
7. Non-regression:
- apply existant inchange,
- check_duplicates gate conserve,
- anti double apply conserve.

## 11) Risques et mitigation
Risque A: collision de chemins au rollback.
- Mitigation: jamais overwrite, quarantaine undo.

Risque B: operation partiellement reversible.
- Mitigation: marquage `reversible=false`, visible en preview.

Risque C: perf sur gros batch.
- Mitigation: insert operationnel batche + index minimal.

## 12) Ordre d'implementation recommande
1. Migration DB v5 + store methods.
2. Hook `record_op` dans core (sans changer logique).
3. Instrumentation `apply` API + persistance batch.
4. Endpoint preview undo.
5. Endpoint undo (dry-run puis reel).
6. Tests unitaires + integration.
7. UI minimale (bouton preview/undo dans Apply) en lot suivant.

## 13) Definition of Done (7.2.0-A)
- Migration v5 appliquee et backward compatible.
- Endpoints undo disponibles et testes.
- Undo dry-run + reel fonctionnels sur cas simples.
- Resume undo lisible.
- Suite tests verte + smoke manuel cible.
