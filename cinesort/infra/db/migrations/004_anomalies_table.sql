PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS anomalies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  row_id TEXT,
  severity TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  path TEXT,
  recommended_action TEXT,
  context_json TEXT,
  ts REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anomalies_run_id
ON anomalies(run_id);

CREATE INDEX IF NOT EXISTS idx_anomalies_severity
ON anomalies(severity);

