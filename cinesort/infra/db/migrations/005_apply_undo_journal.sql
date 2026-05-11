-- v5: journalisation des applies pour prise en charge Undo (7.2.0-A)

CREATE TABLE IF NOT EXISTS apply_batches (
  batch_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  started_ts REAL NOT NULL,
  ended_ts REAL,
  dry_run INTEGER NOT NULL CHECK (dry_run IN (0, 1)),
  quarantine_unapproved INTEGER NOT NULL CHECK (quarantine_unapproved IN (0, 1)),
  status TEXT NOT NULL,
  summary_json TEXT NOT NULL,
  app_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_apply_batches_run_id
ON apply_batches(run_id, started_ts DESC);

CREATE TABLE IF NOT EXISTS apply_operations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  op_index INTEGER NOT NULL,
  op_type TEXT NOT NULL,
  src_path TEXT NOT NULL,
  dst_path TEXT NOT NULL,
  reversible INTEGER NOT NULL CHECK (reversible IN (0, 1)),
  undo_status TEXT NOT NULL DEFAULT 'PENDING',
  error_message TEXT,
  ts REAL NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES apply_batches(batch_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_apply_ops_batch_opindex
ON apply_operations(batch_id, op_index);

CREATE INDEX IF NOT EXISTS idx_apply_ops_batch
ON apply_operations(batch_id, id);

CREATE INDEX IF NOT EXISTS idx_apply_ops_reversible
ON apply_operations(batch_id, reversible);

PRAGMA user_version = 5;
