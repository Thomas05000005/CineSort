-- v8: cache par vidéo individuelle pour scan incrémental v2

CREATE TABLE IF NOT EXISTS incremental_row_cache (
  root_path TEXT NOT NULL,
  video_path TEXT NOT NULL,
  video_size INTEGER NOT NULL,
  video_mtime_ns INTEGER NOT NULL,
  video_hash TEXT NOT NULL,
  folder_path TEXT NOT NULL,
  nfo_sig TEXT DEFAULT NULL,
  cfg_sig TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'single',
  row_json TEXT NOT NULL,
  updated_ts REAL NOT NULL,
  last_run_id TEXT DEFAULT NULL,
  PRIMARY KEY (root_path, video_path)
);

CREATE INDEX IF NOT EXISTS idx_incr_row_folder
  ON incremental_row_cache(root_path, folder_path);

PRAGMA user_version = 8;
