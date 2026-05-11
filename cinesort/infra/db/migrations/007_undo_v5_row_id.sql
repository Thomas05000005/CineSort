-- v7: ajout row_id aux operations apply pour undo film par film (Undo v5)

ALTER TABLE apply_operations ADD COLUMN row_id TEXT DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_apply_ops_row_id
  ON apply_operations(batch_id, row_id);

PRAGMA user_version = 7;
