PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS perceptual_reports (
  run_id TEXT NOT NULL,
  row_id TEXT NOT NULL,
  visual_score INTEGER NOT NULL,
  audio_score INTEGER NOT NULL,
  global_score INTEGER NOT NULL,
  global_tier TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  settings_json TEXT NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY(run_id, row_id)
);

CREATE INDEX IF NOT EXISTS idx_perceptual_reports_run
ON perceptual_reports(run_id);
