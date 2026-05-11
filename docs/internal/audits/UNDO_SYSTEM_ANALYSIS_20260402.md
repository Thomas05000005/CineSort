# CineSort Undo System - Comprehensive Analysis

## Overview
The undo system in CineSort is designed to reverse the last "apply" operation (file moves/renames). It operates in two phases:
1. **Preview Phase**: Check what can be undone
2. **Execution Phase**: Actually reverse the operations (with optional dry-run)

---

## 1. DATABASE SCHEMA (`cinesort/infra/db/migrations/005_apply_undo_journal.sql`)

### v5: Journalisation des applies pour prise en charge Undo (7.2.0-A)

#### Table: `apply_batches`
- **Primary Key**: `batch_id` (TEXT)
- **Columns**:
  - `batch_id` TEXT PRIMARY KEY
  - `run_id` TEXT NOT NULL
  - `started_ts` REAL NOT NULL
  - `ended_ts` REAL (nullable)
  - `dry_run` INTEGER (0 or 1)
  - `quarantine_unapproved` INTEGER (0 or 1)
  - `status` TEXT NOT NULL
  - `summary_json` TEXT NOT NULL
  - `app_version` TEXT NOT NULL
- **Index**: `idx_apply_batches_run_id` on (run_id, started_ts DESC)

#### Table: `apply_operations`
- **Primary Key**: `id` INTEGER AUTOINCREMENT
- **Columns**:
  - `id` INTEGER PRIMARY KEY AUTOINCREMENT
  - `batch_id` TEXT NOT NULL (FK to apply_batches.batch_id)
  - `op_index` INTEGER NOT NULL
  - `op_type` TEXT NOT NULL (e.g., "MOVE", "MOVE_DIR")
  - `src_path` TEXT NOT NULL (original location)
  - `dst_path` TEXT NOT NULL (destination location after apply)
  - `reversible` INTEGER (0 or 1)
  - `undo_status` TEXT NOT NULL DEFAULT 'PENDING'
  - `error_message` TEXT (nullable)
  - `ts` REAL NOT NULL
- **Indexes**:
  - `idx_apply_ops_batch_opindex` UNIQUE (batch_id, op_index)
  - `idx_apply_ops_batch` (batch_id, id)
  - `idx_apply_ops_reversible` (batch_id, reversible)

---

## 2. DATABASE MIXIN (`cinesort/infra/db/_apply_mixin.py`)

### Method: `insert_apply_batch()`
- **Location**: Lines 14-50
- **Purpose**: Create a new apply batch record in the database
- **Parameters**:
  - `run_id: str` - Identifier for the run
  - `dry_run: bool` - Whether this is a test run
  - `quarantine_unapproved: bool` - Isolation mode flag
  - `status: str` - Initial status (default "PENDING")
  - `summary: Optional[Dict[str, Any]]` - Optional metadata JSON
  - `app_version: str` - Application version (default "unknown")
  - `started_ts: Optional[float]` - Start timestamp (auto-generated if None)
  - `batch_id: Optional[str]` - Batch ID (auto-generated if None)
- **Returns**: `str` - The generated or provided batch_id
- **SQL Used**:
  ```sql
  INSERT INTO apply_batches(
    batch_id, run_id, started_ts, ended_ts, dry_run,
    quarantine_unapproved, status, summary_json, app_version
  )
  VALUES(?, ?, ?, NULL, ?, ?, ?, ?, ?)
  ```
- **Logic**:
  - Auto-generates batch_id from millisecond timestamp + UUID hex if not provided
  - Converts boolean flags to 0/1 integers
  - Serializes summary dict to JSON with sorted keys
  - Sets `ended_ts` to NULL initially

### Method: `append_apply_operation()`
- **Location**: Lines 52-83
- **Purpose**: Log a single file operation during apply execution
- **Parameters**:
  - `batch_id: str` - Which batch this operation belongs to
  - `op_index: int` - Sequential operation number within batch
  - `op_type: str` - Type of operation (e.g., "MOVE", "MOVE_DIR")
  - `src_path: str` - Source path (where file was before apply)
  - `dst_path: str` - Destination path (where file is after apply)
  - `reversible: bool` - Whether this operation can be reversed
  - `ts: Optional[float]` - Timestamp (auto-generated if None)
- **Returns**: `int` - The auto-incremented operation ID
- **SQL Used**:
  ```sql
  INSERT INTO apply_operations(
    batch_id, op_index, op_type, src_path, dst_path, reversible, undo_status, error_message, ts
  )
  VALUES(?, ?, ?, ?, ?, ?, 'PENDING', NULL, ?)
  ```
- **Logic**:
  - Auto-generates timestamp from current time if not provided
  - Initializes `undo_status` to 'PENDING' and `error_message` to NULL
  - Returns the database-generated row ID

### Method: `close_apply_batch()`
- **Location**: Lines 85-104
- **Purpose**: Finalize a batch by updating its status and summary
- **Parameters**:
  - `batch_id: str` - The batch to close
  - `status: str` - Final status (e.g., "DONE", "FAILED")
  - `summary: Optional[Dict[str, Any]]` - Updated summary JSON
  - `ended_ts: Optional[float]` - End timestamp (auto-generated if None)
- **Returns**: None
- **SQL Used**:
  ```sql
  UPDATE apply_batches
  SET status=?, ended_ts=?, summary_json=?
  WHERE batch_id=?
  ```
- **Logic**:
  - Serializes summary to JSON with sorted keys
  - Sets end timestamp to current time if not provided

### Method: `get_last_reversible_apply_batch()`
- **Location**: Lines 106-138
- **Purpose**: Fetch the most recent non-dry-run DONE batch for a given run
- **Parameters**:
  - `run_id: str` - The run to query
- **Returns**: `Optional[Dict[str, Any]]` - Batch metadata or None if no batch found
- **SQL Used**:
  ```sql
  SELECT batch_id, run_id, started_ts, ended_ts, dry_run, quarantine_unapproved, status, summary_json, app_version
  FROM apply_batches
  WHERE run_id=? AND dry_run=0 AND status='DONE'
  ORDER BY started_ts DESC
  LIMIT 1
  ```
- **Return Structure**:
  ```python
  {
    "batch_id": str,
    "run_id": str,
    "started_ts": float,
    "ended_ts": Optional[float],
    "dry_run": int (0 or 1),
    "quarantine_unapproved": int (0 or 1),
    "status": str,
    "summary": dict (parsed from JSON),
    "app_version": str,
  }
  ```
- **Logic**:
  - Filters for non-dry-run, completed batches only
  - Parses JSON summary with fallback to empty dict on parse error
  - Returns most recent batch first

### Method: `list_apply_operations()`
- **Location**: Lines 140-167
- **Purpose**: Retrieve all operations for a given batch
- **Parameters**:
  - `batch_id: str` - The batch to query
- **Returns**: `List[Dict[str, Any]]` - List of operation records
- **SQL Used**:
  ```sql
  SELECT id, batch_id, op_index, op_type, src_path, dst_path, reversible, undo_status, error_message, ts
  FROM apply_operations
  WHERE batch_id=?
  ORDER BY op_index ASC, id ASC
  ```
- **Return Structure** (per operation):
  ```python
  {
    "id": int,
    "batch_id": str,
    "op_index": int,
    "op_type": str,
    "src_path": str,
    "dst_path": str,
    "reversible": int (0 or 1),
    "undo_status": str,
    "error_message": str,
    "ts": float,
  }
  ```
- **Logic**:
  - Orders results by operation index and ID to ensure consistent retrieval order
  - Reversible operations are essential for undo to work

### Method: `mark_apply_operation_undo_status()`
- **Location**: Lines 169-185
- **Purpose**: Update the undo status of a single operation
- **Parameters**:
  - `op_id: int` - The operation ID to update
  - `undo_status: str` - New status (e.g., "DONE", "FAILED", "SKIPPED")
  - `error_message: Optional[str]` - Optional error details
- **Returns**: None
- **SQL Used**:
  ```sql
  UPDATE apply_operations
  SET undo_status=?, error_message=?
  WHERE id=?
  ```
- **Logic**:
  - Updates status and error message in one atomic operation
  - Used during undo execution to track progress of each operation

### Method: `mark_apply_batch_undo_status()`
- **Location**: Lines 187-199
- **Purpose**: Mark the undo completion status of an entire batch
- **Parameters**:
  - `batch_id: str` - The batch to update
  - `status: str` - Final status (e.g., "UNDONE_DONE", "UNDONE_PARTIAL")
  - `summary: Optional[Dict[str, Any]]` - Undo execution summary
- **Returns**: None
- **Logic**:
  - Delegates to `close_apply_batch()` with current timestamp
  - Updates both status and summary_json in one call

---

## 3. API SUPPORT MODULE (`cinesort/ui/api/apply_support.py`)

### Function: `build_undo_preview_payload()`
- **Location**: Lines 41-132
- **Purpose**: Prepare comprehensive preview data for undo operation
- **Parameters**:
  - `api: Any` - CineSortApi instance
  - `run_id: str` - The run to analyze
- **Returns**: 
  ```python
  Tuple[
    Dict[str, Any],  # Payload dict
    Optional[SQLiteStore],  # Database store
    Optional[state.RunPaths],  # Run directory paths
    Optional[Dict[str, Any]],  # Batch metadata
    List[Dict[str, Any]],  # Reversible operations
  ]
  ```
- **Payload Structure**:
  ```python
  {
    "ok": bool,
    "run_id": str,
    "batch_id": Optional[str],
    "can_undo": bool,
    "counts": {
      "total": int,         # Total operations
      "reversible": int,    # Reversible operations
      "irreversible": int,  # Non-reversible operations
      "conflicts_predicted": int,  # Predicted conflicts
    },
    "categories": {
      "empty_folder_dirs": int,        # Operations affecting _Vide
      "cleanup_residual_dirs": int,    # Operations affecting _Dossier Nettoyage
    },
    "paths": {
      "empty_folder_bucket": str,          # Path to _Vide
      "cleanup_residual_bucket": str,      # Path to _Dossier Nettoyage
    },
    "message": str,
  }
  ```
- **Logic Flow**:
  1. Find run in database; return error if not found
  2. Get last reversible (non-dry-run, DONE) apply batch
  3. If no batch exists, return can_undo=False with message
  4. Fetch all operations for the batch
  5. Filter operations marked as reversible (reversible=1)
  6. Detect predicted conflicts: compare dst_path (current location) with src_path (undo target)
     - If both exist: conflict predicted
  7. Categorize operations:
     - Count operations moving items to _Vide bucket
     - Count operations moving items to _Dossier Nettoyage bucket
  8. Return comprehensive preview data

### Function: `undo_last_apply_preview()`
- **Location**: Lines 135-143
- **Purpose**: Public API wrapper for preview generation
- **Parameters**:
  - `api: Any` - CineSortApi instance
  - `run_id: str` - The run to analyze
- **Returns**: `Dict[str, Any]` - Preview payload (same structure as build_undo_preview_payload)
- **Logic**:
  - Validates run_id format
  - Calls build_undo_preview_payload and returns only the first element (payload)
  - Catches all exceptions and returns error response

### Function: `_execute_undo_ops()`
- **Location**: Lines 146-230
- **Purpose**: Execute the actual file operations to reverse an apply
- **Parameters**:
  - `api: Any` - CineSortApi instance
  - `reversible_ops: List[Dict[str, Any]]` - Operations to reverse
  - `store: Any` - Database store for status updates
  - `log_fn: Callable[[str, str], None]` - Logging function
  - `run_paths: Any` - Run directory paths (for conflict output)
  - `empty_bucket: Optional[Path]` - Path to _Vide folder
  - `residual_bucket: Optional[Path]` - Path to _Dossier Nettoyage folder
- **Returns**: 
  ```python
  {
    "done": int,                              # Successfully reversed operations
    "skipped": int,                           # Operations skipped (source missing)
    "failed": int,                            # Operations that failed
    "conflict_moves": int,                    # Conflicts moved to review folder
    "empty_folder_dirs_reversed": int,        # _Vide operations reversed
    "cleanup_residual_dirs_reversed": int,    # _Dossier Nettoyage operations reversed
    "undo_conflicts_root": str,               # Path to conflict directory
  }
  ```
- **Critical Logic** (processes operations in REVERSE order):
  1. For each operation (reversed order - last applied first):
     a. Get current_path = dst_path (where file is after apply)
     b. Get target_path = src_path (where file should be after undo)
     c. If current_path doesn't exist:
        - Mark as SKIPPED with message
        - Log warning
        - Continue (no file to reverse)
     d. If target_path exists (CONFLICT):
        - Create `_review/_undo_conflicts` directory if needed
        - Move current_path to unique location in _review/_undo_conflicts
        - Mark operation as FAILED with conflict message
        - Increment conflict_moves counter
        - Continue
     e. If target_path doesn't exist (NORMAL CASE):
        - Create parent directories of target_path
        - Move current_path to target_path using shutil.move
        - Mark operation as DONE
        - Track if file came from empty_bucket or residual_bucket
        - Increment done counter
     f. On any exception:
        - Mark operation as FAILED with error message
        - Log error
        - Increment failed counter
- **Key Design Decisions**:
  - Processes operations in reverse order (LIFO)
  - Conflicts are isolated rather than overwritten
  - Each operation status is recorded in database for auditability
  - Partial failures are allowed (some ops succeed, some fail)

### Function: `_write_undo_summary()`
- **Location**: Lines 233-267
- **Purpose**: Write human-readable undo summary to run's summary.txt file
- **Parameters**:
  - `api: Any` - CineSortApi instance
  - `run_paths: Any` - Run directory paths
  - `log_fn: Callable[[str, str], None]` - Logging function
  - `batch_id: str` - The batch that was undone
  - `counts: Dict[str, int]` - Operation counts (done, skipped, failed, irreversible)
  - `preview_categories: Dict[str, Any]` - Category counts from preview
- **Returns**: None
- **Summary Structure**:
  ```
  === RESUME UNDO ===
  Batch cible: {batch_id}
  Operations restaurees: {done}
  Operations skippees: {skipped}
  Operations en echec: {failed}
  Operations irreversibles: {irreversible}
  [Optional: Dossiers vides (_Vide) inclus...]
  [Optional: Dossiers residuels (_Dossier Nettoyage)...]
  [Optional: Conflits undo deplaces...]
  ```
- **Logic**:
  - Builds summary lines with operation counts
  - Conditionally includes category information if counts > 0
  - Includes conflict path if conflicts occurred
  - Writes to run_paths.summary_txt via api._write_summary_section()
  - Catches all exceptions and logs warning instead of failing

### Function: `undo_last_apply()`
- **Location**: Lines 270-399
- **Purpose**: Main public API for executing undo operations
- **Parameters**:
  - `api: Any` - CineSortApi instance
  - `run_id: str` - The run to undo
  - `dry_run: bool` - If True, only simulate (default True)
- **Returns**: 
  ```python
  {
    "ok": bool,
    "run_id": str,
    "batch_id": str,
    "dry_run": bool,
    "status": str,  # "PREVIEW_ONLY", "NOOP", "UNDONE_DONE", "UNDONE_PARTIAL"
    "counts": {
      "done": int,
      "skipped": int,
      "failed": int,
      "irreversible": int,
    },
    "categories": {
      "empty_folder_dirs": int,
      "cleanup_residual_dirs": int,
      "empty_folder_dirs_reversed": int,  # Only in non-dry-run
      "cleanup_residual_dirs_reversed": int,  # Only in non-dry-run
    },
    "preview": Dict[str, int],  # Original preview counts
    "message": str,
  }
  ```
- **Return Status Values**:
  - `PREVIEW_ONLY`: dry_run=True (no actual changes made)
  - `NOOP`: No reversible operations found
  - `UNDONE_DONE`: Undo completed without failures
  - `UNDONE_PARTIAL`: Undo completed with some failures
- **Execution Flow**:
  1. Validate run_id format
  2. Call build_undo_preview_payload to get batch and operations
  3. If preview not ok, return preview error
  4. If batch/store/run_paths None, return noop response
  5. Calculate irreversible operation count
  6. If dry_run=True:
     - Return preview-only response without executing
     - Status = "PREVIEW_ONLY"
  7. If no reversible operations:
     - Return NOOP response
  8. Get file logger for logging
  9. Log undo start with batch_id and run_id
  10. Call _execute_undo_ops() to perform reversals
  11. Extract operation counts and conflict info
  12. Determine final status:
      - UNDONE_DONE if failed == 0
      - UNDONE_PARTIAL if failed > 0
  13. Build summary payload with full undo statistics
  14. Call store.mark_apply_batch_undo_status() to record final state
  15. Call _write_undo_summary() to write human-readable summary
  16. Return complete result with all counts and categories
- **Error Handling**:
  - Catches exceptions and returns error response
  - Logs exception to API exception handler
  - Returns user-friendly French error messages

---

## 4. PUBLIC API (`cinesort/ui/api/cinesort_api.py`)

### Method: `undo_last_apply_preview()`
- **Location**: Lines 717-718
- **Signature**:
  ```python
  def undo_last_apply_preview(self, run_id: str) -> Dict[str, Any]
  ```
- **What it does**: Delegates to apply_support.undo_last_apply_preview()
- **Returns**: Preview payload with can_undo, counts, and categories

### Method: `undo_last_apply()`
- **Location**: Lines 720-721
- **Signature**:
  ```python
  def undo_last_apply(self, run_id: str, dry_run: bool = True) -> Dict[str, Any]
  ```
- **What it does**: Delegates to apply_support.undo_last_apply()
- **Parameters**:
  - `run_id: str` - The run to undo
  - `dry_run: bool` - Test mode (default True)
- **Returns**: Execution result with status, counts, and categories

### Method: `_build_undo_preview_payload()`
- **Location**: Lines 709-715
- **Signature**:
  ```python
  def _build_undo_preview_payload(self, run_id: str) -> Tuple[...]
  ```
- **Returns**: Full tuple with payload, store, paths, batch, operations
- **Used by**: JavaScript code via window.pywebview.api

---

## 5. JAVASCRIPT UI (`web/app.js`)

### State Management
- **Global state tracking** (Lines 22-23):
  ```javascript
  undoInFlight: false,      // True while preview/execution in progress
  undoPreview: null,        // Currently cached preview data
  ```

### Function: `formatUndoPreview()`
- **Location**: Lines 1655-1684
- **Purpose**: Format preview data for display in result panel
- **Renders**:
  ```
  Run: {run_id}
  Batch cible: {batch_id}
  Undo possible: {can_undo ? "oui" : "non"}
  
  - Opérations journalisées: {total}
  - Opérations réversibles: {reversible}
  - Opérations irréversibles: {irreversible}
  - Conflits prévus: {conflicts_predicted}
  
  [Optional dossiers section if categories > 0]
  Message: {message}
  ```

### Function: `formatUndoExecution()`
- **Location**: Lines 1686-1718
- **Purpose**: Format execution result for display
- **Parameters**:
  - `result: Object` - Undo execution response
  - `dryRun: bool` - Whether this was dry-run
- **Renders**:
  ```
  [Annulation en mode test | Annulation réelle]
  Run: {run_id}
  Batch: {batch_id}
  Statut: {status}
  
  - Restaurées: {done}
  - Skipées: {skipped}
  - Échecs: {failed}
  - Irréversibles: {irreversible}
  
  [Optional dossiers section]
  Message: {message}
  ```

### Function: `updateUndoRunButton()`
- **Location**: Lines 1720-1803
- **Purpose**: Update undo button state and badge display
- **Badge states**:
  - "warn"/"À préparer" - No run loaded yet
  - "warn"/"En attente" - Run loaded but execution in progress
  - "warn"/"Chargement" - Preview fetch in progress
  - "ok"/"Disponible" - Undo ready to execute
  - "warn"/"Indisponible" - No reversible operations
- **Button disabled when**:
  - Preview not loaded (can't undo)
  - Apply or undo already in flight
  - Dry-run checkbox unchecked AND no real undo available

### Function: `refreshUndoPreview()`
- **Location**: Lines 1805-1849
- **Purpose**: Fetch and cache undo preview from API
- **Parameters**:
  - `triggerEl: Element` - Button element for feedback
  - `opts: Object` - Options (silent mode)
- **Flow**:
  1. Validate active run ID
  2. Set undoInFlight=true
  3. Call window.pywebview.api.undo_last_apply_preview(runId)
  4. If response not ok, store null and show error
  5. If ok, cache preview in state.undoPreview
  6. Display formatted preview using formatUndoPreview()
  7. Flash button with ok/error status
  8. Set undoInFlight=false
- **Silent mode**: Doesn't show loading message (used for background refresh)

### Function: `runUndoFromUI()`
- **Location**: Lines 1851-1923
- **Purpose**: Execute undo operation with user confirmation
- **Flow**:
  1. Check if already in flight (preview or execution)
  2. Validate active run ID
  3. Get dry_run checkbox state
  4. If NOT dry-run:
     - Re-fetch preview (silent) to ensure latest state
     - If preview not ok or can_undo not true, reject
     - Show confirmation dialog with danger warning
     - If user cancels, abort
  5. Set undoInFlight=true
  6. Call window.pywebview.api.undo_last_apply(runId, dry_run)
  7. If response not ok, show error
  8. If ok, check status:
     - UNDONE_PARTIAL = partial success (show warning)
     - Otherwise show success
  9. Display formatted result using formatUndoExecution()
  10. Refresh preview (silent) to show post-undo state
  11. Set undoInFlight=false
- **Confirmation Dialog** (for non-dry-run):
  - Title: "Confirmer l'annulation réelle"
  - Message: "Cette action va tenter de restaurer le dernier apply réel. Les conflits seront isolés dans _review/_undo_conflicts."
  - Danger flag: true (red styling)

### Function: `setUndoControlsState()`
- **Location**: Lines 1790-1803
- **Purpose**: Enable/disable undo controls based on state
- **Disables when**:
  - No active run
  - ApplyInFlight or undoInFlight
  - Dry-run unchecked AND no real undo available

### Button Event Listeners
- **#btnUndoPreview**: Calls refreshUndoPreview()
- **#btnUndoRun**: Calls runUndoFromUI()
- **#ckUndoDryRun**: Checkbox for test mode (default checked)

### Home Dashboard Integration
- **Lines 671, 697, 1020-1031**: 
  - On dashboard load, fetch undo_last_apply_preview
  - Extract undoAvailable from response
  - Display as "Disponible" or "Indisponible"
  - Updates state.homeOverview.undoAvailable

---

## 6. HTML STRUCTURE (`web/index.html`)

### Undo Section
- **Location**: Lines 1667-1681
- **Element IDs**:
  - `#btnUndoPreview` - Preview button
  - `#ckUndoDryRun` - Dry-run checkbox (checked by default)
  - `#btnUndoRun` - Execute button
  - `#undoMsg` - Status message span (aria-live)
  - `#undoResult` - Result display (pre element with logbox class)

### Home Dashboard Undo Display
- **Line 250**: `#homeRunUndoText` - Undo status in home overview
- **Line 697**: Hidden JavaScript update

### Quality Module Undo Display
- **Line 757**: `#qualityRunUndoText` - Undo status in quality dashboard
- **Line 833-839**: JavaScript fetch and display

### Dashboard Undo Display
- **Line 1975**: `#dashRunUndoText` - Undo status in run report

### Apply Rail Status
- **Lines 1703-1709**: 
  - `#applyRailUndoBadge` - Undo availability badge
  - `#applyRailUndoHint` - Undo hint text
  - States: "À préparer", "En attente", "Chargement", "Disponible", "Indisponible"

### Undo Documentation
- **Lines 1778-1787**: Help section with guidance:
  - "Garder l'undo en second temps, jamais en réflexe."
  - "Prévisualiser avant tout undo réel."
  - "L'undo ne force jamais l'écrasement d'une cible existante."
  - Recommends using dry-run first (mode test)

---

## 7. PREVIEW API (`web/preview/preview_api.js`)

### Function: `undoPreviewFor()`
- **Location**: Lines 212-235
- **Purpose**: Mock undo preview for local preview mode
- **Returns**:
  ```javascript
  {
    ok: true,
    run_id: runId,
    batch_id: "preview-none",
    can_undo: false,
    undo_available: false,
    counts: { total: 0, reversible: 0, irreversible: 0, conflicts_predicted: 0 },
    categories: { empty_folder_dirs: 0, cleanup_residual_dirs: 0 },
    message: "Aucun undo disponible pour ce scenario."
  }
  ```
- **Mock data**:
  - Always returns no undo available initially
  - Updated when apply() is simulated (see below)

### Function: `simulatePlanRun()`
- **Location**: Lines 303-349
- **Creates mock undo preview after simulated apply**:
  - Sets can_undo=false initially
  - Updated in apply() when non-dry-run executed

### Function: `apply()` Mock
- **Location**: Lines 535-577
- **Updates undo preview on non-dry-run** (Lines 542-559):
  ```javascript
  store.undoPreviewByRunId[rid] = {
    ok: true,
    run_id: rid,
    batch_id: "preview-apply-live",
    can_undo: true,
    undo_available: true,
    counts: {
      total: Math.max(1, appliedCount),
      reversible: Math.max(1, appliedCount),
      irreversible: 0,
      conflicts_predicted: 0,
    },
    categories: {
      empty_folder_dirs: 1,
      cleanup_residual_dirs: 1,
    },
    message: "Apply preview memorise pour undo.",
  };
  ```

### Function: `undo_last_apply_preview()`
- **Location**: Lines 503-505
- **Purpose**: Mock API endpoint
- **Returns**: Result of undoPreviewFor()

### Function: `undo_last_apply()`
- **Location**: Lines 579-609
- **Purpose**: Mock API endpoint for undo execution
- **Parameters**:
  - `runId: str` - Run ID
  - `dryRun: bool` - Test mode
- **Behavior**:
  - Retrieves current preview data
  - If dryRun=false AND can_undo=true:
    - Updates run history (applied_rows = 0)
    - Sets can_undo=false for future
  - Returns mock response with status "DRY_RUN" or "UNDONE"
- **Returns**:
  ```javascript
  {
    ok: true,
    run_id: rid,
    batch_id: String(preview.batch_id || "preview-apply-live"),
    status: dryRun ? "DRY_RUN" : "UNDONE",
    counts: {
      done: Number(preview.counts.reversible || 0),
      skipped: 0,
      failed: 0,
      irreversible: Number(preview.counts.irreversible || 0),
    },
    categories: {
      empty_folder_dirs_reversed: Number(preview.categories.empty_folder_dirs || 0),
      cleanup_residual_dirs_reversed: Number(preview.categories.cleanup_residual_dirs || 0),
    },
    message: dryRun ? "Undo teste en preview." : "Undo simule termine.",
  }
  ```

---

## 8. KNOWN LIMITATIONS & EDGE CASES

### Handled Cases
1. ✓ Missing source file during undo → marked SKIPPED
2. ✓ Destination conflict during undo → moved to _review/_undo_conflicts
3. ✓ Partial operation failures → status UNDONE_PARTIAL
4. ✓ Irreversible operations → counted separately, not reversed
5. ✓ Empty folder and cleanup residual operations → tracked separately
6. ✓ Dry-run mode → preview without changes
7. ✓ Database journal failures → operations logged with best effort
8. ✓ Reversed operation order → LIFO (last applied first)

### NOT Handled / Limitations
1. ✗ Multi-level undo (only last batch can be undone)
2. ✗ Selective undo (all or nothing per batch)
3. ✗ Undo of partial applies (only complete DONE batches)
4. ✗ Overwrite existing target files (conflicts moved instead)
5. ✗ Symlink handling during undo (no special logic)
6. ✗ Permission errors (will be caught as FAILED)
7. ✗ Disk space validation before undo
8. ✗ Undo of undo (no cascading reversal)

### Edge Cases with Special Handling
1. **Dry-run applies**: Not included in last_reversible search (dry_run=0 filter)
2. **Failed applies**: Operations may not be in database if batch creation failed
3. **Concurrent undos**: Prevented by undoInFlight flag in UI
4. **Conflict resolution**: Automatically moves to _review/_undo_conflicts with unique naming
5. **Empty_folder_dirs**: Special category for _Vide operations (reversible)
6. **cleanup_residual_dirs**: Special category for _Dossier Nettoyage operations (reversible)

### TODO Comments & Known Issues
- **Line 735-741 in apply_support.py**: Empty folder and cleanup residual operations explicitly noted as "inclus dans l'undo du run" (included in run undo)
- No explicit TODOs in undo code, but preview mode in JS indicates potential future enhancements

---

## 9. DATA FLOW SUMMARY

```
PREVIEW FLOW:
1. User clicks "Prévisualiser l'annulation"
2. JavaScript calls window.pywebview.api.undo_last_apply_preview(runId)
3. CineSortApi.undo_last_apply_preview() → apply_support.undo_last_apply_preview()
4. Gets last reversible batch and operations from database
5. Analyzes conflicts (dst_path exists + src_path exists = conflict)
6. Counts operations by category
7. Returns preview with can_undo, counts, categories
8. JavaScript displays formatted preview in #undoResult
9. Updates button state based on can_undo flag

EXECUTION FLOW (dry-run):
1. User keeps dry-run checked and clicks "Lancer l'annulation"
2. JavaScript calls window.pywebview.api.undo_last_apply(runId, dry_run=true)
3. apply_support.undo_last_apply() builds preview again
4. Returns response with status="PREVIEW_ONLY"
5. No database updates, no file moves
6. JavaScript displays result without re-enabling undo

EXECUTION FLOW (real):
1. User unchecks dry-run and clicks "Lancer l'annulation"
2. JavaScript fetches fresh preview (silent mode)
3. Shows confirmation dialog warning about reversibility
4. User confirms, calls window.pywebview.api.undo_last_apply(runId, dry_run=false)
5. apply_support.undo_last_apply():
   a. Gets operations in REVERSE order
   b. For each operation: move dst_path → src_path
   c. Update operation undo_status in database
   d. Handle conflicts by moving to _review/_undo_conflicts
   e. Update batch status to UNDONE_DONE or UNDONE_PARTIAL
   f. Write summary to summary.txt
6. Returns result with counts and status
7. JavaScript displays result and auto-refreshes preview
8. Undo becomes unavailable (batch marked as undone)
```

---

## 10. RESPONSE EXAMPLES

### Successful Preview Response
```json
{
  "ok": true,
  "run_id": "run_20240101_abc123",
  "batch_id": "1704067200000_xyz789",
  "can_undo": true,
  "counts": {
    "total": 150,
    "reversible": 145,
    "irreversible": 5,
    "conflicts_predicted": 3
  },
  "categories": {
    "empty_folder_dirs": 8,
    "cleanup_residual_dirs": 12
  },
  "paths": {
    "empty_folder_bucket": "D:\\Films\\_Vide",
    "cleanup_residual_bucket": "D:\\Films\\_Dossier Nettoyage"
  },
  "message": "Preview undo pret."
}
```

### Successful Dry-Run Execution Response
```json
{
  "ok": true,
  "run_id": "run_20240101_abc123",
  "batch_id": "1704067200000_xyz789",
  "dry_run": true,
  "status": "PREVIEW_ONLY",
  "counts": {
    "done": 0,
    "skipped": 0,
    "failed": 0,
    "irreversible": 5
  },
  "categories": {
    "empty_folder_dirs": 8,
    "cleanup_residual_dirs": 12,
    "empty_folder_dirs_reversed": 0,
    "cleanup_residual_dirs_reversed": 0
  },
  "preview": {
    "total": 150,
    "reversible": 145,
    "irreversible": 5,
    "conflicts_predicted": 3
  },
  "message": "Previsualisation de l'annulation uniquement (mode test)."
}
```

---

END OF ANALYSIS
