-- v19 audit QA 20260429 : journal write-ahead pour atomicite shutil.move (CR-1).
-- Insertion AVANT chaque move, suppression APRES move reussi. Si l'app crashe
-- entre INSERT et DELETE, l'entree reste pour reconciliation au prochain boot.
--
-- Conception : table simple, pas de FK vers apply_batches (les pending peuvent
-- etre creees AVANT le batch DONE et survivre a un crash batch). batch_id est
-- juste une etiquette pour grouper en cas de besoin de cleanup manuel.

CREATE TABLE IF NOT EXISTS apply_pending_moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    TEXT,
    op_type     TEXT NOT NULL,        -- MOVE_FILE | MOVE_DIR | QUARANTINE_FILE | QUARANTINE_DIR
    src_path    TEXT NOT NULL,
    dst_path    TEXT NOT NULL,
    src_sha1    TEXT,
    src_size    INTEGER,
    row_id      TEXT,
    ts          REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_apply_pending_moves_batch
    ON apply_pending_moves(batch_id);

CREATE INDEX IF NOT EXISTS idx_apply_pending_moves_ts
    ON apply_pending_moves(ts);

PRAGMA user_version = 19;
