PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS quality_profiles (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  profile_json TEXT NOT NULL,
  created_ts REAL NOT NULL,
  updated_ts REAL NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_quality_profiles_active
ON quality_profiles(is_active);

CREATE TABLE IF NOT EXISTS quality_reports (
  run_id TEXT NOT NULL,
  row_id TEXT NOT NULL,
  score INTEGER NOT NULL,
  tier TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  profile_version INTEGER NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY(run_id, row_id)
);

CREATE INDEX IF NOT EXISTS idx_quality_reports_run
ON quality_reports(run_id);

