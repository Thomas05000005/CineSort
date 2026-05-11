-- v6: cache de scan incrémental (7.2.0-B)

CREATE TABLE IF NOT EXISTS incremental_file_hashes (
  path TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  quick_hash TEXT NOT NULL,
  updated_ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incremental_file_hashes_lookup
ON incremental_file_hashes(path, size, mtime_ns);

CREATE TABLE IF NOT EXISTS incremental_scan_cache (
  root_path TEXT NOT NULL,
  folder_path TEXT NOT NULL,
  cfg_sig TEXT NOT NULL,
  folder_sig TEXT NOT NULL,
  rows_json TEXT NOT NULL,
  stats_json TEXT NOT NULL,
  updated_ts REAL NOT NULL,
  last_run_id TEXT,
  PRIMARY KEY (root_path, folder_path)
);

CREATE INDEX IF NOT EXISTS idx_incremental_scan_cache_root
ON incremental_scan_cache(root_path, updated_ts DESC);

PRAGMA user_version = 6;
